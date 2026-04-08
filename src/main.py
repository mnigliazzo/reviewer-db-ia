import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from .skill_middleware import load_skills_from_disk

logger = logging.getLogger(__name__)

SKILLS_BASE_PATH = Path(__file__).parent / "skills"


@dataclass
class SqlScript:
    migration: str      # nombre de la carpeta de migración, ej: "20260407112400"
    file: Path
    is_rollback: bool


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
      2. carpeta de migración (orden lexicográfico = cronológico por timestamp)
      3. scripts forward primero, rollback después
      4. nombre de archivo (orden numérico por prefijo NNN)
    """
    scripts: list[SqlScript] = []

    for year_dir in sorted(p for p in scripts_path.iterdir() if p.is_dir()):
        for migration_dir in sorted(p for p in year_dir.iterdir() if p.is_dir()):
            # Scripts forward (hijos directos)
            for sql_file in sorted(migration_dir.glob("*.sql")):
                scripts.append(SqlScript(migration_dir.name, sql_file, is_rollback=False))

            # Scripts de rollback
            rollback_dir = migration_dir / "rollback"
            if rollback_dir.is_dir():
                for sql_file in sorted(rollback_dir.glob("*.sql")):
                    scripts.append(SqlScript(migration_dir.name, sql_file, is_rollback=True))

    return scripts


def build_system_prompt() -> str:
    skills = load_skills_from_disk(str(SKILLS_BASE_PATH))
    skills_content = "\n\n---\n\n".join(
        f"## Skill: {s['name']}\n\n{s['content']}" for s in skills
    )
    return (
        "You are an expert SQL Server DBA and T-SQL code reviewer.\n"
        "Your task is to review SQL scripts and provide structured, actionable feedback.\n"
        "IMPORTANT: Always respond in Spanish (castellano).\n"
        "IMPORTANT: Never use Markdown formatting. This means:\n"
        "  - No # or ## or ### or #### for headings\n"
        "  - No ** or * for bold or italic\n"
        "  - No backticks or ``` for code blocks\n"
        "  - No > for blockquotes\n"
        "  - No --- as separators\n"
        "Instead, use UPPERCASE plain text for section titles and indent with spaces.\n\n"
        "Use this exact output format:\n"
        "RESUMEN\n"
        "  Seguridad:       X/10\n"
        "  Rendimiento:     X/10\n"
        "  Mantenibilidad:  X/10\n\n"
        "HALLAZGOS\n\n"
        "  [PRIORIDAD] [CATEGORIA]: Titulo del hallazgo\n"
        "  Ubicacion: ...\n"
        "  Riesgo: ...\n"
        "  Recomendacion: ...\n\n"
        "Apply the following review guidelines:\n\n"
        f"{skills_content}"
    )


def review_sql_file(model: ChatOllama, system_prompt: str, script: SqlScript) -> str:
    sql_content = script.file.read_text(encoding="utf-8")
    script_type = "ROLLBACK" if script.is_rollback else "FORWARD MIGRATION"
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                f"Revisa el siguiente script de SQL Server.\n"
                f"Migracion: {script.migration} | Tipo: {script_type} | Archivo: {script.file.name}\n\n"
                f"{sql_content}\n\n"
                "Responde UNICAMENTE en texto plano sin ningun simbolo Markdown. "
                "Usa el formato indicado en las instrucciones del sistema."
            )
        ),
    ]
    response = model.invoke(messages)
    return response.content


def main():
    parser = argparse.ArgumentParser(description="CI SQL Reviewer powered by AI")
    parser.add_argument("--scripts-path", type=str, required=True, help="Path to the migration scripts root folder")
    parser.add_argument("--ollama-url", type=str, required=True, help="Ollama API URL")
    parser.add_argument("--model-agent", type=str, required=True, help="AI Model name")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
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

    forward = sum(1 for s in scripts if not s.is_rollback)
    rollback = sum(1 for s in scripts if s.is_rollback)
    logger.info(f"Found {len(scripts)} SQL script(s) — {forward} forward, {rollback} rollback")

    logger.info(f"Initializing SQL Reviewer — model: {args.model_agent}")
    model = ChatOllama(base_url=args.ollama_url, model=args.model_agent, num_ctx=16384)
    system_prompt = build_system_prompt()

    has_critical = False
    current_migration = None

    for script in scripts:
        # Imprimir encabezado de migración cuando cambia
        if script.migration != current_migration:
            current_migration = script.migration
            print(f"\n{'#' * 60}")
            print(f"MIGRATION: {current_migration}")
            print(f"{'#' * 60}")

        script_label = f"[ROLLBACK] {script.file.name}" if script.is_rollback else script.file.name
        logger.info(f"Reviewing: {current_migration}/{script_label}")

        try:
            review = review_sql_file(model, system_prompt, script)
        except Exception as e:
            logger.error(f"Failed to review {script_label}: {e}")
            has_critical = True
            continue

        print(f"\n{'=' * 60}")
        print(f"{'[ROLLBACK] ' if script.is_rollback else ''}REVIEW: {script.file.name}")
        print("=" * 60)
        print(review)

        # Heurística para detectar problemas críticos en CI
        review_upper = review.upper()
        critical_markers = ["[CRITICAL]", "[HIGH]", "CRITICAL:", "HIGH PRIORITY", "PRIORIDAD ALTA"]
        if any(marker in review_upper for marker in critical_markers):
            has_critical = True
            logger.warning(f"Critical issues detected in {script_label}")

    if has_critical:
        logger.error("One or more scripts have critical issues. Review the output above.")
        sys.exit(1)

    logger.info("All SQL scripts reviewed successfully.")


if __name__ == "__main__":
    main()
