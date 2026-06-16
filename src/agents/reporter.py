from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from .reviewer import _load_prompt

logger = logging.getLogger(__name__)


class ReporterAgent:
    """
    Genera el informe ejecutivo global consolidando los mini-informes
    por migración producidos por MiniReporterAgent.
    """

    def __init__(self, model: BaseChatModel):
        self._model = model
        self._system_prompt = _load_prompt("reporter_system.md")

    def report(self, migration_reports: list[str]) -> str:
        if not migration_reports:
            return "No hay informes de migración para consolidar."

        reports_text = "\n\n".join(
            f"--- Migración {i + 1} ---\n{report}"
            for i, report in enumerate(migration_reports)
        )

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=(
                f"Consolida los siguientes {len(migration_reports)} informes de migración "
                f"en un informe ejecutivo final:\n\n{reports_text}"
            )),
        ]

        logger.info("ReporterAgent generando informe ejecutivo final")
        return self._model.invoke(messages).content
