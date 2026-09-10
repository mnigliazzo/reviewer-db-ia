from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..models import CoherenceOutput, MigrationReport, ScriptReview
from .base import load_prompt

logger = logging.getLogger(__name__)


class MiniReporterAgent:
    """Genera el ``MigrationReport`` de una migración: métricas calculadas desde los
    hallazgos estructurados + un resumen narrativo del LLM."""

    def __init__(self, model: BaseChatModel):
        self._model = model
        self._system_prompt = load_prompt("mini_reporter_system.md")

    def generate(
        self,
        migration_id: str,
        reviews: list[ScriptReview],
        coherence: CoherenceOutput | None,
    ) -> MigrationReport:
        context = "\n\n".join(
            f"--- {r.script.file.name} ---\n{r.result.render()}" for r in reviews
        )
        if coherence is not None:
            context += f"\n\n=== COHERENCIA ===\n{coherence.render()}"

        logger.info(f"MiniReporterAgent generando resumen para migración {migration_id}")
        resumen = self._model.invoke([
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=f"Migración: {migration_id}\n\n{context}"),
        ]).text.strip()

        return MigrationReport.build(migration_id, reviews, coherence, resumen)
