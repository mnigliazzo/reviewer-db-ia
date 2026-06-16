import argparse
import logging
import sys
from pathlib import Path

from .agents import CoherenceAgent, MiniReporterAgent, ReporterAgent, ReviewerAgent
from .graph import build_pipeline_graph
from .models import SqlScript

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("ollama", "openai", "openrouter", "groq")

PROVIDER_DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def build_model(provider: str, base_url: str, model: str, api_key: str | None = None):
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(base_url=base_url, model=model, num_ctx=16384)
    elif provider in ("openai", "openrouter", "groq"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=base_url or PROVIDER_DEFAULT_URLS[provider],
            model=model,
            api_key=api_key or "sk-no-key",
        )
    else:
        raise ValueError(f"Provider no soportado: '{provider}'. Opciones: {SUPPORTED_PROVIDERS}")


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


def main():
    parser = argparse.ArgumentParser(description="CI SQL Reviewer powered by AI (multi-agente)")
    parser.add_argument("--scripts-path",  type=str, required=True,  help="Path to the migration scripts root folder")
    parser.add_argument("--provider",      type=str, default="ollama", choices=SUPPORTED_PROVIDERS, help="LLM provider")
    parser.add_argument("--base-url",      type=str, required=True,  help="Base URL del LLM provider")
    parser.add_argument("--model-agent",   type=str, required=True,  help="AI Model name")
    parser.add_argument("--api-key",       type=str,                 help="API key (requerido para providers cloud)")
    parser.add_argument("--skip-reporter", action="store_true",      help="Omitir informe ejecutivo final")
    parser.add_argument("--log-level",     type=str, default="INFO", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    scripts_path = Path(args.scripts_path)
    if not scripts_path.exists():
        logger.error(f"Scripts path does not exist: {scripts_path}")
        sys.exit(1)

    scripts = discover_scripts(scripts_path)
    if not scripts:
        logger.warning(f"No .sql files found under {scripts_path}")
        sys.exit(0)

    forward  = sum(1 for s in scripts if not s.is_rollback)
    rollback = sum(1 for s in scripts if s.is_rollback)
    logger.info(f"Found {len(scripts)} SQL script(s) — {forward} forward, {rollback} rollback")

    logger.info(f"Initializing agents — provider: {args.provider}  model: {args.model_agent}")
    model          = build_model(args.provider, args.base_url, args.model_agent, args.api_key)
    pipeline_graph = build_pipeline_graph(
        reviewer        = ReviewerAgent(model, SKILLS_BASE_PATH),
        coherence_agent = CoherenceAgent(model),
        mini_reporter_agent = MiniReporterAgent(model),
        reporter_agent  = ReporterAgent(model) if not args.skip_reporter else None,
    )

    migrations: dict[str, list[SqlScript]] = {}
    for script in scripts:
        migrations.setdefault(script.migration, []).append(script)

    migrations_queue = [
        (
            migration_id,
            [(s, s.file.read_text(encoding="utf-8")) for s in migration_scripts if not s.is_rollback],
            [(s.file.name, s.file.read_text(encoding="utf-8")) for s in migration_scripts if s.is_rollback],
        )
        for migration_id, migration_scripts in migrations.items()
    ]

    result = pipeline_graph.invoke({
        "migrations_queue": migrations_queue,
        "previous_scripts": [],
        "all_reviews": [],
        "migration_reports": [],
        "incoherent_migrations": [],
        "has_critical": False,
        "final_report": "",
    })

    if result.get("has_critical") or result.get("incoherent_migrations"):
        if result.get("has_critical"):
            critical = [r.script.file.name for r in result["all_reviews"] if r.result.has_critical]
            logger.error(f"Hallazgos CRÍTICOS en: {', '.join(critical)}")
        if result.get("incoherent_migrations"):
            logger.error(f"Rollback INCOMPLETO en migraciones: {', '.join(result['incoherent_migrations'])}")
        logger.error("Pipeline finalizado con errores — revisar hallazgos antes de mergear.")
        sys.exit(1)

    logger.info("All SQL scripts reviewed successfully.")


if __name__ == "__main__":
    main()
