from __future__ import annotations

import logging
import operator
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from .agents import CoherenceAgent, MiniReporterAgent, ReviewerAgent
from .logging_utils import banner
from .models import ScriptReview

logger = logging.getLogger(__name__)


# ── Per-migration state ────────────────────────────────────────────────────────

class MigrationState(TypedDict):
    migration_id: str
    schema_context: str
    scripts_to_review: list                               # [(SqlScript, sql_content), ...]
    rollback_scripts_data: list                           # pre-cargado, solo para coherence
    reviews: Annotated[list, operator.add]                # mergeado de workers paralelos
    forward_scripts_data: Annotated[list, operator.add]   # mergeado de workers paralelos
    has_critical: Annotated[bool, operator.or_]           # OR de todos los workers
    coherence_report: str
    coherence_approved: bool
    mini_report: str


def build_migration_graph(
    reviewer: ReviewerAgent,
    coherence_agent: CoherenceAgent,
    mini_reporter_agent: MiniReporterAgent,
):
    def fan_out_fn(state: MigrationState):
        scripts = state.get("scripts_to_review", [])
        if not scripts:
            return "coherence"
        return [
            Send("review_script", {
                "migration_id": state["migration_id"],
                "schema_context": state["schema_context"],
                "script": script,
                "sql_content": sql_content,
            })
            for script, sql_content in scripts
        ]

    def review_script_node(worker: dict) -> dict:
        """Worker paralelo: carga skills y pide el review estructurado de un script."""
        script = worker["script"]
        sql_content = worker["sql_content"]

        logger.info(f"Reviewing: {worker['migration_id']}/{script.file.name}")

        result = reviewer.review(script, sql_content, worker.get("schema_context", ""))
        sr = ScriptReview(script=script, result=result)

        banner(logger, f"REVIEW: {script.file.name}")
        logger.info(f"Skills usadas: {', '.join(result.skills_utilizadas) or 'ninguna'}")
        logger.info(result.render())

        return {
            "reviews": [sr],
            "forward_scripts_data": [(script.file.name, sql_content)],
            "has_critical": result.has_critical,
        }

    def gather_node(state: MigrationState) -> dict:
        """Fan-in: corre una vez después de que todos los workers terminan."""
        return {}

    def route_after_gather(state: MigrationState) -> str:
        return "escalate" if state.get("has_critical") else "coherence"

    def coherence_node(state: MigrationState) -> dict:
        mid = state["migration_id"]
        forward = state.get("forward_scripts_data", [])
        if not forward:
            return {
                "coherence_report": f"MIGRACION: {mid}\n\nNo hay scripts de despliegue forward para analizar.",
                "coherence_approved": True,
            }
        output = coherence_agent.analyze(mid, forward, state.get("rollback_scripts_data", []))
        report = output.render()
        banner(logger, f"COHERENCIA: {mid}", "~")
        logger.info(report)
        if not output.approved:
            logger.warning(f"Rollback incompleto detectado en migración {mid}")
        return {"coherence_report": report, "coherence_approved": output.approved}

    def mini_reporter_node(state: MigrationState) -> dict:
        mid = state["migration_id"]
        try:
            report = mini_reporter_agent.report(
                mid,
                state.get("reviews", []),
                state.get("coherence_report", ""),
                state.get("coherence_approved", True),
            )
        except Exception:  # noqa: BLE001 - el informe es informativo, no bloquea
            logger.exception(f"El mini-informe de {mid} falló")
            report = f"(No se pudo generar el informe de la migración {mid}.)"
        banner(logger, f"INFORME MIGRACIÓN: {mid}", "*")
        logger.info(report)
        return {"mini_report": report}

    def escalate_node(state: MigrationState) -> dict:
        critical = [r.script.file.name for r in state.get("reviews", []) if r.result.has_critical]
        logger.error(f"ESCALATE — Hallazgos CRÍTICOS en {state['migration_id']}: {', '.join(critical)}")
        return {}

    graph = StateGraph(MigrationState)
    graph.add_node("fan_out", lambda s: {})
    graph.add_node("review_script", review_script_node)
    graph.add_node("gather", gather_node)
    graph.add_node("coherence", coherence_node)
    graph.add_node("mini_reporter", mini_reporter_node)
    graph.add_node("escalate", escalate_node)

    graph.add_edge(START, "fan_out")
    graph.add_conditional_edges("fan_out", fan_out_fn, ["review_script", "coherence"])
    graph.add_edge("review_script", "gather")
    graph.add_conditional_edges("gather", route_after_gather, {
        "escalate": "escalate",
        "coherence": "coherence",
    })
    graph.add_edge("escalate", END)
    graph.add_edge("coherence", "mini_reporter")
    graph.add_edge("mini_reporter", END)

    return graph.compile()


def build_schema_context(previous_scripts: list[tuple[str, str]], max_scripts: int = 10) -> str:
    """Contexto para el reviewer: los scripts forward ya revisados de migraciones
    anteriores (los últimos ``max_scripts``; ``0`` = todos)."""
    if not previous_scripts:
        return ""
    recent = previous_scripts[-max_scripts:] if max_scripts > 0 else previous_scripts
    blocks = "\n\n".join(f"--- {name} ---\n{content}" for name, content in recent)
    return f"CONTEXTO - scripts SQL anteriores de esta migración:\n\n{blocks}"


def new_migration_state(migration_id: str, schema_context: str, forward_scripts: list, rollback_data: list) -> dict:
    """Estado inicial para una corrida de ``build_migration_graph().invoke()``."""
    return {
        "migration_id": migration_id,
        "schema_context": schema_context,
        "scripts_to_review": forward_scripts,
        "rollback_scripts_data": rollback_data,
        "reviews": [],
        "forward_scripts_data": [],
        "has_critical": False,
        "coherence_report": "",
        "coherence_approved": True,
        "mini_report": "",
    }
