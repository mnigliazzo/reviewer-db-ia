from __future__ import annotations

import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from .agents import CoherenceAgent, MiniReporterAgent, ReviewerAgent
from .logging_utils import banner
from .models import CoherenceOutput, MigrationReport, ScriptReview

logger = logging.getLogger(__name__)

# El modelo a veces termina el turno sin emitir la salida estructurada
# (structured_response=None -> RuntimeError) o la emite mal (ValidationError).
# Es no-determinista: reintentar el nodo suele resolverlo. Errores de red también.
_LLM_RETRY = RetryPolicy(
    max_attempts=3,
    retry_on=(RuntimeError, ValueError, ConnectionError, TimeoutError),
)


class MigrationState(TypedDict):
    migration_id: str
    schema_context: str
    scripts_to_review: list                               # [(SqlScript, sql_content), ...]
    rollback_scripts_data: list                           # [(nombre, contenido), ...]
    reviews: Annotated[list, operator.add]                # mergeado del fan-out
    forward_scripts_data: Annotated[list, operator.add]   # mergeado del fan-out
    coherence: CoherenceOutput | None
    report: MigrationReport | None


def build_migration_graph(
    reviewer: ReviewerAgent,
    coherence_agent: CoherenceAgent,
    mini_reporter_agent: MiniReporterAgent,
):
    """``START -(Send fan-out)-> review_script -> coherence -> mini_reporter -> END``.

    ``coherence`` corre una sola vez tras el fan-in implícito de los ``review_script``
    paralelos. Se invoca una vez por migración (vía ``.batch()`` desde ``main``).
    """

    def fan_out(state: MigrationState) -> list[Send]:
        return [
            Send("review_script", {
                "migration_id": state["migration_id"],
                "schema_context": state["schema_context"],
                "script": script,
                "sql_content": sql_content,
            })
            for script, sql_content in state["scripts_to_review"]
        ]

    def review_script_node(worker: dict) -> dict:
        script, sql_content = worker["script"], worker["sql_content"]
        logger.info(f"Reviewing: {worker['migration_id']}/{script.file.name}")

        result = reviewer.review(script, sql_content, worker["schema_context"])

        banner(logger, f"REVIEW: {script.file.name}")
        logger.info(f"Skills usadas: {', '.join(result.skills_utilizadas) or 'ninguna'}")
        logger.info(result.render())

        return {
            "reviews": [ScriptReview(script=script, result=result)],
            "forward_scripts_data": [(script.file.name, sql_content)],
        }

    def coherence_node(state: MigrationState) -> dict:
        mid = state["migration_id"]
        output = coherence_agent.analyze(
            mid, state["forward_scripts_data"], state["rollback_scripts_data"]
        )
        banner(logger, f"COHERENCIA: {mid}", "~")
        logger.info(output.render())
        if not output.approved:
            logger.warning(f"Rollback incompleto detectado en migración {mid}")
        return {"coherence": output}

    def mini_reporter_node(state: MigrationState) -> dict:
        mid = state["migration_id"]
        try:
            report = mini_reporter_agent.generate(mid, state["reviews"], state["coherence"])
        except Exception:  # noqa: BLE001 - el informe es informativo, no bloquea
            logger.exception(f"El informe de la migración {mid} falló")
            report = MigrationReport.build(
                mid, state["reviews"], state["coherence"],
                "(No se pudo generar el resumen ejecutivo.)",
            )
        banner(logger, f"INFORME MIGRACIÓN: {mid}", "*")
        logger.info(report.render())
        return {"report": report}

    graph = StateGraph(MigrationState)
    graph.add_node("review_script", review_script_node, retry_policy=_LLM_RETRY)
    graph.add_node("coherence", coherence_node, retry_policy=_LLM_RETRY)
    graph.add_node("mini_reporter", mini_reporter_node)

    graph.add_conditional_edges(START, fan_out, ["review_script"])
    graph.add_edge("review_script", "coherence")
    graph.add_edge("coherence", "mini_reporter")
    graph.add_edge("mini_reporter", END)

    return graph.compile()


def build_schema_context(previous_scripts: list[tuple[str, str]], max_scripts: int = 10) -> str:
    """Contexto para el reviewer: los scripts forward de migraciones anteriores
    (los últimos ``max_scripts``; ``0`` = todos)."""
    if not previous_scripts:
        return ""
    recent = previous_scripts[-max_scripts:] if max_scripts > 0 else previous_scripts
    blocks = "\n\n".join(f"--- {name} ---\n{content}" for name, content in recent)
    return f"CONTEXTO - scripts SQL anteriores de esta migración:\n\n{blocks}"


def build_migration_states(migrations: list[tuple], max_schema_scripts: int = 0) -> list[MigrationState]:
    """Estados iniciales para ``migration_graph.batch(...)``, uno por migración con
    scripts forward. El ``schema_context`` de cada una son los forward de las
    anteriores (conocidos de antemano)."""
    states: list[MigrationState] = []
    seen: list[tuple[str, str]] = []
    for migration_id, forward_scripts, rollback_data in migrations:
        if not forward_scripts:
            logger.warning(f"Migración {migration_id} sin scripts forward — se omite")
            continue
        states.append({
            "migration_id": migration_id,
            "schema_context": build_schema_context(seen, max_schema_scripts),
            "scripts_to_review": forward_scripts,
            "rollback_scripts_data": rollback_data,
            "reviews": [],
            "forward_scripts_data": [],
            "coherence": None,
            "report": None,
        })
        seen += [(script.file.name, sql) for script, sql in forward_scripts]
    return states
