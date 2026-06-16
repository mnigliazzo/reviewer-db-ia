from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..models import ScriptReview
from .reviewer import _load_prompt

logger = logging.getLogger(__name__)


class MiniReporterAgent:
    """
    Genera un informe resumido por migración: estadísticas, estado del rollback
    y hallazgos críticos/altos. Su salida es la entrada del ReporterAgent global.
    """

    def __init__(self, model: BaseChatModel):
        self._model = model
        self._system_prompt = _load_prompt("mini_reporter_system.md")

    def report(
        self,
        migration_id: str,
        reviews: list[ScriptReview],
        coherence_report: str,
        coherence_approved: bool,
    ) -> str:
        reviews_text = "\n\n".join(
            f"--- {r.script.file.name} ---\n{r.review}" for r in reviews
        )
        coherence_section = coherence_report or "(Análisis de coherencia no disponible)"

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=(
                f"Migración: {migration_id}\n\n"
                f"=== REVIEWS DE SCRIPTS ===\n\n{reviews_text}\n\n"
                f"=== ANÁLISIS DE COHERENCIA ===\n\n{coherence_section}"
            )),
        ]

        logger.info(f"MiniReporterAgent generando informe para migración {migration_id}")
        return self._model.invoke(messages).content
