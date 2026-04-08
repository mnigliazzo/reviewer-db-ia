"""
Grafo LangGraph para el pipeline de revisión de un script SQL.

Flujo:
    START
      ↓
  [reviewer]  ←──────────────────┐
      ↓                          │ retry
  [validator]                    │
      ↓                          │
  ¿aprobado o sin reintentos? ───┘
      ↓ done
     END
"""
from __future__ import annotations

import logging
from typing import Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .agents import ReviewerAgent, ValidatorAgent
from .models import SqlScript

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Estado compartido entre nodos
# ---------------------------------------------------------------------------

class ReviewState(TypedDict):
    # Input (inmutable durante el grafo)
    script: SqlScript
    max_retries: int

    # Seguimiento
    attempts: int
    validator_feedback: Optional[str]

    # Output acumulado
    review: str
    approved: bool


# ---------------------------------------------------------------------------
# Construcción del grafo
# ---------------------------------------------------------------------------

def build_review_graph(reviewer: ReviewerAgent, validator: ValidatorAgent):
    """
    Construye y compila el StateGraph de revisión.
    Recibe las instancias de agente como closure para que los nodos
    puedan llamarlos sin necesitar acceso global.
    """

    # --- Nodos ---

    def reviewer_node(state: ReviewState) -> dict:
        logger.debug(f"[reviewer_node] intento {state['attempts'] + 1} — {state['script'].file.name}")
        review = reviewer.review(
            state["script"],
            validator_feedback=state.get("validator_feedback"),
        )
        return {
            "review": review,
            "attempts": state["attempts"] + 1,
        }

    def validator_node(state: ReviewState) -> dict:
        logger.debug(f"[validator_node] evaluando review de {state['script'].file.name}")
        result = validator.validate(state["script"], state["review"])

        if result.approved:
            logger.info(f"  Validacion: APROBADO (intento {state['attempts']})")
        else:
            logger.warning(f"  Validacion: RECHAZADO — {result.feedback[:80]}...")

        return {
            "approved": result.approved,
            "validator_feedback": result.feedback if not result.approved else None,
        }

    # --- Edge condicional ---

    def should_retry(state: ReviewState) -> str:
        if state["approved"]:
            return "done"
        if state["attempts"] > state["max_retries"]:
            logger.warning("  Se agotaron los reintentos. Usando el último review disponible.")
            return "done"
        logger.info(f"  Reintento {state['attempts']}/{state['max_retries']} para {state['script'].file.name}")
        return "retry"

    # --- Construcción del grafo ---

    graph = StateGraph(ReviewState)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("validator", validator_node)

    graph.add_edge(START, "reviewer")
    graph.add_edge("reviewer", "validator")
    graph.add_conditional_edges(
        "validator",
        should_retry,
        {"retry": "reviewer", "done": END},
    )

    return graph.compile()
