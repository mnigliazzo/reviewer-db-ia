from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..models import ScriptReview
from .reviewer import _load_prompt

logger = logging.getLogger(__name__)


class ReporterAgent:
    """
    Agente reportero: consolida todos los reviews individuales en un
    informe ejecutivo final con métricas y prioridades globales.

    Se ejecuta una sola vez al final, luego de que todos los scripts
    fueron revisados y validados.
    """

    def __init__(self, model: BaseChatModel):
        self._model = model
        self._system_prompt = _load_prompt("reporter_system.md")

    def report(self, reviews: list[ScriptReview]) -> str:
        """Genera el informe ejecutivo consolidado."""
        if not reviews:
            return "No hay reviews para consolidar."

        reviews_text = ""
        for i, sr in enumerate(reviews, 1):
            label = f"[ROLLBACK] {sr.script.file.name}" if sr.script.is_rollback else sr.script.file.name
            reviews_text += (
                f"--- Script {i}: {sr.script.migration}/{label} ---\n"
                f"{sr.review}\n\n"
            )

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(
                content=(
                    f"Consolida los siguientes {len(reviews)} reviews en un informe ejecutivo:\n\n"
                    f"{reviews_text}"
                )
            ),
        ]

        logger.info("ReporterAgent generando informe ejecutivo final")
        return self._model.invoke(messages).content
