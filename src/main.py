import argparse
import json
import logging
import sys
from pathlib import Path

from .agents import CoherenceAgent, MiniReporterAgent, ReporterAgent, ReviewerAgent
from .graph import build_pipeline_graph
from .llm import CLOUD_PROVIDERS, SUPPORTED_PROVIDERS, build_model, resilient
from .models import PRIORIDADES, ScriptReview, SqlScript
from .sarif import to_sarif

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

SKILLS_BASE_PATH = Path(__file__).parent / "skills"


def discover_scripts(scripts_path: Path) -> list[SqlScript]:
    """
    Recorre la estructura:
        <scripts_path>/
            <YEAR>/
                <MIGRATION_FOLDER>/
                    NNN.Script.sql
                    rollback/
                        NNN.Script.sql
    """
    scripts: list[SqlScript] = []

    for year_dir in sorted(p for p in scripts_path.iterdir() if p.is_dir()):
        for migration_dir in sorted(p for p in year_dir.iterdir() if p.is_dir()):
            for sql_file in sorted(migration_dir.glob("*.sql")):
                scripts.append(SqlScript(migration_dir.name, sql_file, is_rollback=False))

            rollback_dir = next(
                (d for d in migration_dir.iterdir() if d.is_dir() and d.name.lower() == "rollback"),
                None,
            )
            if rollback_dir:
                for sql_file in sorted(rollback_dir.glob("*.sql")):
                    scripts.append(SqlScript(migration_dir.name, sql_file, is_rollback=True))

    return scripts


def _read_text(path: Path) -> str | None:
    """Lee un archivo SQL como UTF-8. Devuelve ``None`` (y loguea) si falla."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.error(f"No se pudo leer {path}: {exc}")
        return None


def build_migrations_queue(scripts: list[SqlScript]) -> list[tuple]:
    """Agrupa los scripts por migración y precarga su contenido una sola vez.

    Cada entrada de la cola es
    ``(migration_id, [(SqlScript, contenido), ...], [(nombre, contenido), ...])``
    con los forward y los rollback ya leídos en memoria.
    """
    migrations: dict[str, list[SqlScript]] = {}
    for script in scripts:
        migrations.setdefault(script.migration, []).append(script)

    queue: list[tuple] = []
    for migration_id, migration_scripts in migrations.items():
        forward: list[tuple[SqlScript, str]] = []
        rollback: list[tuple[str, str]] = []
        for s in migration_scripts:
            content = _read_text(s.file)
            if content is None:
                continue
            if s.is_rollback:
                rollback.append((s.file.name, content))
            else:
                forward.append((s, content))
        queue.append((migration_id, forward, rollback))
    return queue


def decide_exit(
    all_reviews: list[ScriptReview],
    incoherent_migrations: list[str],
    fail_on: set[str],
) -> tuple[int, list[str]]:
    """Decide el exit code según la política ``--fail-on`` + rollback incompleto.

    Devuelve ``(exit_code, motivos)``.
    """
    reasons: list[str] = []

    blocking = [
        f"{r.script.file.name}: [{f.prioridad}] {f.titulo}"
        for r in all_reviews
        for f in r.result.hallazgos
        if f.prioridad in fail_on
    ]
    if blocking:
        reasons.append(
            f"Hallazgos que bloquean ({'/'.join(sorted(fail_on))}): " + "; ".join(blocking)
        )
    if incoherent_migrations:
        reasons.append(
            "Rollback INCOMPLETO en migraciones: " + ", ".join(incoherent_migrations)
        )
    return (1 if reasons else 0), reasons


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CI SQL Reviewer powered by AI (multi-agente)")
    parser.add_argument("--scripts-path",  type=str, required=True,  help="Path to the migration scripts root folder")
    parser.add_argument("--provider",      type=str, default="ollama", choices=SUPPORTED_PROVIDERS, help="LLM provider")
    parser.add_argument("--base-url",      type=str, required=True,  help="Base URL del LLM provider")
    parser.add_argument("--model-agent",   type=str, required=True,  help="AI Model name")
    parser.add_argument("--api-key",       type=str,                 help="API key (requerido para providers cloud)")
    parser.add_argument("--skip-reporter",      action="store_true",  help="Omitir informe ejecutivo final")
    parser.add_argument("--max-tool-rounds",    type=int, default=0, help="Max rondas de tool calls por script (0 = ilimitado)")
    parser.add_argument("--max-schema-scripts", type=int, default=0, help="Max scripts previos en el schema context (0 = ilimitado)")
    parser.add_argument("--temperature",        type=float, default=0.0, help="Temperature del modelo (default 0 = determinista)")
    parser.add_argument("--llm-timeout",        type=float, default=120.0, help="Timeout por llamada al LLM, en segundos")
    parser.add_argument("--llm-retries",        type=int, default=2, help="Reintentos por llamada al LLM ante error transitorio")
    parser.add_argument("--fail-on",            type=str, default="CRÍTICO",
                        help="Prioridades que hacen fallar el pipeline (CSV). Default: CRÍTICO")
    parser.add_argument("--sarif",              type=str, help="Escribe el reporte SARIF 2.1.0 en esta ruta")
    parser.add_argument("--log-level",          type=str, default="INFO", help="Log level")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.provider in CLOUD_PROVIDERS and not args.api_key:
        parser.error(f"--api-key es requerido para el provider '{args.provider}'")
    if args.max_tool_rounds < 0:
        parser.error("--max-tool-rounds no puede ser negativo (0 = ilimitado)")
    if args.max_schema_scripts < 0:
        parser.error("--max-schema-scripts no puede ser negativo (0 = ilimitado)")
    if args.llm_retries < 0:
        parser.error("--llm-retries no puede ser negativo")

    args.fail_on_set = {p.strip().upper() for p in args.fail_on.split(",") if p.strip()}
    unknown = args.fail_on_set - set(PRIORIDADES)
    if unknown:
        parser.error(f"--fail-on: prioridades desconocidas {sorted(unknown)}. Válidas: {list(PRIORIDADES)}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    scripts_path = Path(args.scripts_path)
    if not scripts_path.is_dir():
        logger.error(f"Scripts path does not exist: {scripts_path}")
        return 1

    scripts = discover_scripts(scripts_path)
    if not scripts:
        logger.warning(f"No .sql files found under {scripts_path}")
        return 0

    forward  = sum(1 for s in scripts if not s.is_rollback)
    rollback = sum(1 for s in scripts if s.is_rollback)
    logger.info(f"Found {len(scripts)} SQL script(s) — {forward} forward, {rollback} rollback")

    logger.info(f"Initializing agents — provider: {args.provider}  model: {args.model_agent}")
    model = build_model(
        args.provider, args.base_url, args.model_agent, args.api_key,
        temperature=args.temperature, timeout=args.llm_timeout,
    )
    resilient_model = resilient(model, args.llm_retries)
    pipeline_graph = build_pipeline_graph(
        reviewer            = ReviewerAgent(model, SKILLS_BASE_PATH, retries=args.llm_retries),
        coherence_agent     = CoherenceAgent(model, retries=args.llm_retries),
        mini_reporter_agent = MiniReporterAgent(resilient_model),
        reporter_agent      = ReporterAgent(resilient_model) if not args.skip_reporter else None,
        max_tool_rounds     = args.max_tool_rounds,
        max_schema_scripts  = args.max_schema_scripts,
    )

    migrations_queue = build_migrations_queue(scripts)

    result = pipeline_graph.invoke({
        "migrations_queue": migrations_queue,
        "previous_scripts": [],
        "all_reviews": [],
        "migration_reports": [],
        "incoherent_migrations": [],
        "has_critical": False,
        "final_report": "",
    })

    all_reviews = result.get("all_reviews", [])
    incoherent = result.get("incoherent_migrations", [])

    if args.sarif:
        sarif_path = Path(args.sarif)
        sarif_path.parent.mkdir(parents=True, exist_ok=True)
        sarif_path.write_text(
            json.dumps(to_sarif(all_reviews, incoherent, scripts_path), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Reporte SARIF escrito en {sarif_path}")

    exit_code, reasons = decide_exit(all_reviews, incoherent, args.fail_on_set)
    if exit_code != 0:
        for reason in reasons:
            logger.error(reason)
        logger.error("Pipeline finalizado con errores — revisar hallazgos antes de mergear.")
        return exit_code

    logger.info("All SQL scripts reviewed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
