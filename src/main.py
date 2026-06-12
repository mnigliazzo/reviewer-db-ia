import argparse
import logging
import sys
from pathlib import Path

from .agents import CoherenceAgent, ReporterAgent, ReviewerAgent
from .graph import build_review_graph
from .models import ScriptReview, SqlScript

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
            <YEAR>/                     (ej: 2026)
                <MIGRATION_FOLDER>/     (ej: 20260407112400)
                    NNN.Script.sql
                    rollback/
                        NNN.Script.sql

    Devuelve los scripts ordenados por año, migración, forward primero, nombre de archivo.
    """
    scripts: list[SqlScript] = []

    for year_dir in sorted(p for p in scripts_path.iterdir() if p.is_dir()):
        for migration_dir in sorted(p for p in year_dir.iterdir() if p.is_dir()):
            for sql_file in sorted(migration_dir.glob("*.sql")):
                scripts.append(SqlScript(migration_dir.name, sql_file, is_rollback=False))

            rollback_dir = migration_dir / "rollback"
            if rollback_dir.is_dir():
                for sql_file in sorted(rollback_dir.glob("*.sql")):
                    scripts.append(SqlScript(migration_dir.name, sql_file, is_rollback=True))

    return scripts


def _build_schema_context(previous_scripts: list[tuple[str, str]]) -> str:
    if not previous_scripts:
        return ""
    blocks = "\n\n".join(f"--- {name} ---\n{content}" for name, content in previous_scripts)
    return f"CONTEXTO - scripts SQL anteriores de esta migración:\n\n{blocks}"


def run_review_pipeline(
    script: SqlScript,
    sql_content: str,
    review_graph,
    schema_context: str,
) -> ScriptReview:
    final_state = review_graph.invoke({
        "script": script,
        "sql_content": sql_content,
        "schema_context": schema_context,
        "messages": [],
        "skills_used": [],
    })
    return ScriptReview(
        script=script,
        review=final_state["messages"][-1].content,
        skills_used=final_state.get("skills_used", []),
    )


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
    model        = build_model(args.provider, args.base_url, args.model_agent, args.api_key)
    reviewer     = ReviewerAgent(model, SKILLS_BASE_PATH)
    coherence    = CoherenceAgent(model)
    reporter     = ReporterAgent(model) if not args.skip_reporter else None
    review_graph = build_review_graph(reviewer)

    all_reviews: list[ScriptReview] = []
    previous_scripts: list[tuple[str, str]] = []

    migrations: dict[str, list[SqlScript]] = {}
    for script in scripts:
        migrations.setdefault(script.migration, []).append(script)

    for migration_id, migration_scripts in migrations.items():
        logger.info(f"{'#' * 60}")
        logger.info(f"MIGRATION: {migration_id}")
        logger.info(f"{'#' * 60}")

        forward_scripts_data:  list[tuple[str, str]] = []
        rollback_scripts_data: list[tuple[str, str]] = []

        for script in migration_scripts:
            sql_content = script.file.read_text(encoding="utf-8")

            if script.is_rollback:
                rollback_scripts_data.append((script.file.name, sql_content))
                continue

            logger.info(f"Reviewing: {migration_id}/{script.file.name}")

            try:
                result = run_review_pipeline(
                    script, sql_content, review_graph, _build_schema_context(previous_scripts)
                )
            except Exception as e:
                logger.error(f"Failed to review {script.file.name}: {e}")
                all_reviews.append(ScriptReview(script=script, review=str(e), skills_used=[]))
                continue

            all_reviews.append(result)
            forward_scripts_data.append((script.file.name, sql_content))
            previous_scripts.append((script.file.name, sql_content))

            logger.info(f"{'=' * 60}")
            logger.info(f"REVIEW: {script.file.name}")
            logger.info(f"Skills usadas: {', '.join(result.skills_used) if result.skills_used else 'ninguna'}")
            logger.info(f"{'=' * 60}")
            logger.info(result.review)

        if forward_scripts_data:
            try:
                coherence_result = coherence.analyze(
                    migration_id, forward_scripts_data, rollback_scripts_data
                )
                logger.info(f"{'~' * 60}")
                logger.info(f"COHERENCIA: {migration_id}")
                logger.info(f"{'~' * 60}")
                logger.info(coherence_result.report)
                if not coherence_result.approved:
                    logger.warning(f"Rollback incompleto detectado en migración {migration_id}")
            except Exception as e:
                logger.error(f"CoherenceAgent failed for migration {migration_id}: {e}")

    if reporter:
        logger.info(f"{'#' * 60}")
        logger.info("INFORME EJECUTIVO FINAL")
        logger.info(f"{'#' * 60}")
        try:
            logger.info(reporter.report(all_reviews))
        except Exception as e:
            logger.error(f"ReporterAgent failed: {e}")

    logger.info("All SQL scripts reviewed successfully.")


if __name__ == "__main__":
    main()
