from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .agents import CoherenceAgent, MiniReporterAgent, ReporterAgent, ReviewerAgent
from .models import ScriptReview

logger = logging.getLogger(__name__)


# ── Per-migration state ────────────────────────────────────────────────────────

class MigrationState(TypedDict):
    migration_id: str
    schema_context: str
    pending_scripts: list           # [(SqlScript, sql_content), ...]
    forward_scripts_data: list      # [(name, content), ...] acumulado para coherence
    rollback_scripts_data: list     # [(name, content), ...] pre-cargado, solo para coherence
    reviews: list                   # [ScriptReview, ...]
    has_critical: bool
    current_script: Any
    current_sql: str
    messages: list
    skills_used: list[str]
    coherence_report: str
    coherence_approved: bool
    mini_report: str


def build_migration_graph(
    reviewer: ReviewerAgent,
    coherence_agent: CoherenceAgent,
    mini_reporter_agent: MiniReporterAgent,
):
    def pick_next_script(state: MigrationState) -> dict:
        pending = list(state.get("pending_scripts", []))
        if not pending:
            return {"current_script": None, "pending_scripts": []}
        script, sql_content = pending.pop(0)
        logger.info(f"Reviewing: {state['migration_id']}/{script.file.name}")
        return {
            "pending_scripts": pending,
            "current_script": script,
            "current_sql": sql_content,
            "messages": reviewer.build_messages(script, sql_content, state.get("schema_context", "")),
            "skills_used": [],
        }

    def reviewer_node(state: MigrationState) -> dict:
        response = reviewer.model_with_tools.invoke(state["messages"])
        return {"messages": state["messages"] + [response]}

    def tool_node(state: MigrationState) -> dict:
        last = state["messages"][-1]
        new_skills = list(state.get("skills_used", []))
        tool_messages = []
        for tc in last.tool_calls:
            result = reviewer.load_skill_tool.invoke(tc["args"])
            name = tc["args"].get("skill_name", "")
            if name and name not in new_skills:
                new_skills.append(name)
            tool_messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        return {
            "messages": state["messages"] + tool_messages,
            "skills_used": new_skills,
        }

    def save_review(state: MigrationState) -> dict:
        script = state["current_script"]
        review_text = state["messages"][-1].content
        skills = state.get("skills_used", [])

        sr = ScriptReview(script=script, review=review_text, skills_used=skills)
        reviews = list(state.get("reviews", []))
        reviews.append(sr)

        forward_data = list(state.get("forward_scripts_data", []))
        forward_data.append((script.file.name, state["current_sql"]))

        has_critical = state.get("has_critical", False) or "[CRÍTICO]" in review_text

        logger.info(f"{'=' * 60}")
        logger.info(f"REVIEW: {script.file.name}")
        logger.info(f"Skills usadas: {', '.join(skills) if skills else 'ninguna'}")
        logger.info(f"{'=' * 60}")
        logger.info(review_text)

        return {
            "reviews": reviews,
            "forward_scripts_data": forward_data,
            "has_critical": has_critical,
        }

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
        return {
            "coherence_report": result.report,
            "coherence_approved": result.approved,
        }

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
        critical = [r.script.file.name for r in state.get("reviews", []) if "[CRÍTICO]" in r.review]
        logger.error(f"ESCALATE — Hallazgos CRÍTICOS en {state['migration_id']}: {', '.join(critical)}")
        return {}

    def route_after_pick(state: MigrationState) -> str:
        if state.get("current_script") is not None:
            return "reviewer"
        return "escalate" if state.get("has_critical") else "coherence"

    def route_after_reviewer(state: MigrationState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else "save_review"

    graph = StateGraph(MigrationState)
    graph.add_node("pick_next", pick_next_script)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("tools", tool_node)
    graph.add_node("save_review", save_review)
    graph.add_node("coherence", coherence_node)
    graph.add_node("mini_reporter", mini_reporter_node)
    graph.add_node("escalate", escalate_node)

    graph.add_edge(START, "pick_next")
    graph.add_conditional_edges("pick_next", route_after_pick, {
        "reviewer": "reviewer",
        "coherence": "coherence",
        "escalate": "escalate",
    })
    graph.add_conditional_edges("reviewer", route_after_reviewer, {
        "tools": "tools",
        "save_review": "save_review",
    })
    graph.add_edge("tools", "reviewer")
    graph.add_edge("save_review", "pick_next")
    graph.add_edge("coherence", "mini_reporter")
    graph.add_edge("mini_reporter", END)
    graph.add_edge("escalate", END)

    return graph.compile()


# ── Pipeline state (todas las migraciones) ────────────────────────────────────

class PipelineState(TypedDict):
    migrations_queue: list          # [(migration_id, forward_scripts, rollback_data), ...]
    previous_scripts: list          # [(name, content), ...] acumulado entre migraciones
    all_reviews: list               # [ScriptReview, ...] acumulado
    migration_reports: list         # [str, ...] mini-informes acumulados
    incoherent_migrations: list     # [str, ...] IDs de migraciones con rollback incompleto
    has_critical: bool
    final_report: str


def _build_schema_context(previous_scripts: list[tuple[str, str]]) -> str:
    if not previous_scripts:
        return ""
    blocks = "\n\n".join(f"--- {name} ---\n{content}" for name, content in previous_scripts)
    return f"CONTEXTO - scripts SQL anteriores de esta migración:\n\n{blocks}"


def build_pipeline_graph(
    reviewer: ReviewerAgent,
    coherence_agent: CoherenceAgent,
    mini_reporter_agent: MiniReporterAgent,
    reporter_agent: Optional[ReporterAgent] = None,
):
    migration_graph = build_migration_graph(reviewer, coherence_agent, mini_reporter_agent)

    def run_migration_node(state: PipelineState) -> dict:
        queue = list(state["migrations_queue"])
        migration_id, forward_scripts, rollback_scripts_data = queue.pop(0)

        logger.info(f"{'#' * 60}")
        logger.info(f"MIGRATION: {migration_id}")
        logger.info(f"{'#' * 60}")

        migration_result = migration_graph.invoke({
            "migration_id": migration_id,
            "schema_context": _build_schema_context(state.get("previous_scripts", [])),
            "pending_scripts": forward_scripts,
            "forward_scripts_data": [],
            "rollback_scripts_data": rollback_scripts_data,
            "reviews": [],
            "has_critical": False,
            "current_script": None,
            "current_sql": "",
            "messages": [],
            "skills_used": [],
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
