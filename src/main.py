import argparse
import logging
import sys
from pathlib import Path

from langchain_ollama import ChatOllama

from .agents import ReporterAgent, ReviewerAgent, ValidatorAgent
from .graph import build_review_graph
from .models import ScriptReview, SqlScript

logger = logging.getLogger(__name__)

SKILLS_BASE_PATH = Path(__file__).parent / "skills"
CRITICAL_MARKERS = ["[CRITICAL]", "[HIGH]", "CRITICAL:", "HIGH PRIORITY", "PRIORIDAD ALTA", "[ALTA]"]


# ---------------------------------------------------------------------------
# Descubrimiento de scripts
# ---------------------------------------------------------------------------

def discover_scripts(scripts_path: Path) -> list[SqlScript]:
    """
    Recorre la estructura:
        <scripts_path>/
            <YEAR>/                     (ej: 2026)
                <MIGRATION_FOLDER>/     (ej: 20260407112400)
                    NNN.Script.sql
                    rollback/
                        NNN.Script.sql

    Devuelve los scripts ordenados por:
      1. año
      2. carpeta de migración (cronológico por timestamp)
      3. scripts forward primero, rollback después
      4. nombre de archivo (orden numérico por prefijo NNN)
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


# ---------------------------------------------------------------------------
# Orquestación via LangGraph
# ---------------------------------------------------------------------------

def run_review_pipeline(script: SqlScript, review_graph, max_retries: int) -> ScriptReview:
    """Ejecuta el StateGraph de LangGraph para un script SQL."""
    final_state = review_graph.invoke({
        "script": script,
        "max_retries": max_retries,
        "attempts": 0,
        "validator_feedback": None,
        "review": "",
        "approved": False,
    })
    has_critical = any(m in final_state["review"].upper() for m in CRITICAL_MARKERS)
    return ScriptReview(
        script=script,
        review=final_state["review"],
        attempts=final_state["attempts"],
        has_critical=has_critical,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="CI SQL Reviewer powered by AI (multi-agente)")
    parser.add_argument("--scripts-path",  type=str, required=True,  help="Path to the migration scripts root folder")
    parser.add_argument("--ollama-url",    type=str, required=True,  help="Ollama API URL")
    parser.add_argument("--model-agent",   type=str, required=True,  help="AI Model name")
    parser.add_argument("--max-retries",   type=int, default=1,      help="Reintentos si el validador rechaza (default: 1)")
    parser.add_argument("--skip-reporter", action="store_true",      help="Omitir informe ejecutivo final (más rápido en CPU)")
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

    logger.info(f"Initializing agents — model: {args.model_agent}")
    model        = ChatOllama(base_url=args.ollama_url, model=args.model_agent, num_ctx=16384)
    reviewer     = ReviewerAgent(model, SKILLS_BASE_PATH)
    validator    = ValidatorAgent(model)
    reporter     = ReporterAgent(model) if not args.skip_reporter else None
    review_graph = build_review_graph(reviewer, validator)

    all_reviews: list[ScriptReview] = []
    current_migration = None

    for script in scripts:
        if script.migration != current_migration:
            current_migration = script.migration
            logger.info(f"{'#' * 60}")
            logger.info(f"MIGRATION: {current_migration}")
            logger.info(f"{'#' * 60}")

        script_label = f"[ROLLBACK] {script.file.name}" if script.is_rollback else script.file.name
        logger.info(f"Reviewing: {current_migration}/{script_label}")

        try:
            result = run_review_pipeline(script, review_graph, args.max_retries)
        except Exception as e:
            logger.error(f"Failed to review {script_label}: {e}")
            all_reviews.append(ScriptReview(script=script, review=str(e), attempts=0, has_critical=True))
            continue

        all_reviews.append(result)

        logger.info(f"{'=' * 60}")
        logger.info(f"{'[ROLLBACK] ' if script.is_rollback else ''}REVIEW: {script.file.name}  (intentos: {result.attempts})")
        logger.info(f"{'=' * 60}")
        logger.info(result.review)

        if result.has_critical:
            logger.warning(f"Critical issues detected in {script_label}")

    # Informe ejecutivo final
    if reporter:
        logger.info(f"{'#' * 60}")
        logger.info("INFORME EJECUTIVO FINAL")
        logger.info(f"{'#' * 60}")
        try:
            logger.info(reporter.report(all_reviews))
        except Exception as e:
            logger.error(f"ReporterAgent failed: {e}")

    if any(r.has_critical for r in all_reviews):
        logger.error("One or more scripts have critical issues. Review the output above.")
        sys.exit(1)

    logger.info("All SQL scripts reviewed successfully.")


if __name__ == "__main__":
    main()
