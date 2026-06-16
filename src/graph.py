from __future__ import annotations

import logging
import operator
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from .agents import CoherenceAgent, MiniReporterAgent, ReporterAgent, ReviewerAgent
from .models import ScriptReview, parse_review_text

logger = logging.getLogger(__name__)


def _bool_or(a: bool, b: bool) -> bool:
    return a or b


# ── Per-migration state ────────────────────────────────────────────────────────

class MigrationState(TypedDict):
    migration_id: str
    schema_context: str
    scripts_to_review: list                               # [(SqlScript, sql_content), ...]
    rollback_scripts_data: list                           # pre-cargado, solo para coherence
    reviews: Annotated[list, operator.add]                # mergeado de workers paralelos
    forward_scripts_data: Annotated[list, operator.add]   # mergeado de workers paralelos
    has_critical: Annotated[bool, _bool_or]               # OR de todos los workers
    coherence_report: str
    coherence_approved: bool
    mini_report: str


def build_migration_graph(
    reviewer: ReviewerAgent,
    coherence_agent: CoherenceAgent,
    mini_reporter_agent: MiniReporterAgent,
    max_tool_rounds: int = 0,
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
        """Worker paralelo: maneja un script completo con su loop de tool calls."""
        script = worker["script"]
        sql_content = worker["sql_content"]

        messages = reviewer.build_messages(script, sql_content, worker.get("schema_context", ""))
        skills_used: list[str] = []

        logger.info(f"Reviewing: {worker['migration_id']}/{script.file.name}")

        rounds = 0
        while max_tool_rounds == 0 or rounds < max_tool_rounds:
            rounds += 1
            response = reviewer.model_with_tools.invoke(messages)
            messages.append(response)
            if not getattr(response, "tool_calls", None):
                break
            for tc in response.tool_calls:
                tool_result = reviewer.load_skill_tool.invoke(tc["args"])
                name = tc["args"].get("skill_name", "")
                if name and name not in skills_used:
                    skills_used.append(name)
                messages.append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))

        review_text = messages[-1].content
        result = parse_review_text(review_text, skills_used)
        sr = ScriptReview(script=script, result=result)

        logger.info(f"{'=' * 60}")
        logger.info(f"REVIEW: {script.file.name}")
        logger.info(f"Skills usadas: {', '.join(skills_used) if skills_used else 'ninguna'}")
        logger.info(f"{'=' * 60}")
        logger.info(review_text)

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
        result = coherence_agent.analyze(
            state["migration_id"],
            state.get("forward_scripts_data", []),
            state.get("rollback_scripts_data", []),
        )
        logger.info(f"{'~' * 60}")
        logger.info(f"COHERENCIA: {state['migration_id']}")
        logger.info(f"{'~' * 60}")
        logger.info(result.report)
        if not result.approved:
            logger.warning(f"Rollback incompleto detectado en migración {state['migration_id']}")
        return {"coherence_report": result.report, "coherence_approved": result.approved}

    def mini_reporter_node(state: MigrationState) -> dict:
        report = mini_reporter_agent.report(
            state["migration_id"],
            state.get("reviews", []),
            state.get("coherence_report", ""),
            state.get("coherence_approved", True),
        )
        logger.info(f"{'*' * 60}")
        logger.info(f"INFORME MIGRACIÓN: {state['migration_id']}")
        logger.info(f"{'*' * 60}")
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


# ── Pipeline state (todas las migraciones) ────────────────────────────────────

class PipelineState(TypedDict):
    migrations_queue: list
    previous_scripts: list
    all_reviews: list
    migration_reports: list
    incoherent_migrations: list
    has_critical: bool
    final_report: str


def _build_schema_context(previous_scripts: list[tuple[str, str]], max_scripts: int = 10) -> str:
    if not previous_scripts:
        return ""
    recent = previous_scripts[-max_scripts:] if max_scripts > 0 else previous_scripts
    blocks = "\n\n".join(f"--- {name} ---\n{content}" for name, content in recent)
    return f"CONTEXTO - scripts SQL anteriores de esta migración:\n\n{blocks}"


def build_pipeline_graph(
    reviewer: ReviewerAgent,
    coherence_agent: CoherenceAgent,
    mini_reporter_agent: MiniReporterAgent,
    reporter_agent: Optional[ReporterAgent] = None,
    max_tool_rounds: int = 0,
    max_schema_scripts: int = 0,
):
    migration_graph = build_migration_graph(reviewer, coherence_agent, mini_reporter_agent, max_tool_rounds)

    def run_migration_node(state: PipelineState) -> dict:
        queue = list(state["migrations_queue"])
        migration_id, forward_scripts, rollback_scripts_data = queue.pop(0)

        logger.info(f"{'#' * 60}")
        logger.info(f"MIGRATION: {migration_id}")
        logger.info(f"{'#' * 60}")

        migration_result = migration_graph.invoke({
            "migration_id": migration_id,
            "schema_context": _build_schema_context(state.get("previous_scripts", []), max_schema_scripts),
            "scripts_to_review": forward_scripts,
            "rollback_scripts_data": rollback_scripts_data,
            "reviews": [],
            "forward_scripts_data": [],
            "has_critical": False,
            "coherence_report": "",
            "coherence_approved": True,
            "mini_report": "",
        })

        all_reviews = list(state.get("all_reviews", [])) + migration_result.get("reviews", [])
        previous_scripts = list(state.get("previous_scripts", [])) + migration_result.get("forward_scripts_data", [])

        migration_reports = list(state.get("migration_reports", []))
        if migration_result.get("mini_report"):
            migration_reports.append(migration_result["mini_report"])

        incoherent = list(state.get("incoherent_migrations", []))
        if not migration_result.get("coherence_approved", True):
            incoherent.append(migration_id)

        has_critical = state.get("has_critical", False) or migration_result.get("has_critical", False)

        return {
            "migrations_queue": queue,
            "all_reviews": all_reviews,
            "previous_scripts": previous_scripts,
            "migration_reports": migration_reports,
            "incoherent_migrations": incoherent,
            "has_critical": has_critical,
        }

    def global_reporter_node(state: PipelineState) -> dict:
        if reporter_agent is None:
            return {"final_report": ""}
        logger.info(f"{'#' * 60}")
        logger.info("INFORME EJECUTIVO FINAL")
        logger.info(f"{'#' * 60}")
        report = reporter_agent.report(state.get("migration_reports", []))
        logger.info(report)
        return {"final_report": report}

    def route_after_migration(state: PipelineState) -> str:
        return "run_migration" if state.get("migrations_queue") else "global_reporter"

    pipeline = StateGraph(PipelineState)
    pipeline.add_node("run_migration", run_migration_node)
    pipeline.add_node("global_reporter", global_reporter_node)

    pipeline.add_edge(START, "run_migration")
    pipeline.add_conditional_edges("run_migration", route_after_migration, {
        "run_migration": "run_migration",
        "global_reporter": "global_reporter",
    })
    pipeline.add_edge("global_reporter", END)

    return pipeline.compile()
