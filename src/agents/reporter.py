from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..models import MigrationReport
from .base import load_prompt

logger = logging.getLogger(__name__)


class ReporterAgent:
    """Consolida los ``MigrationReport`` de cada migración en el informe ejecutivo final."""

    def __init__(self, model: BaseChatModel):
        self._model = model
        self._system_prompt = load_prompt("reporter_system.md")

    def summarize(self, reports: list[MigrationReport]) -> str:
        if not reports:
            return "No hay informes de migración para consolidar."

        payload = "\n\n".join(r.render() for r in reports)
        logger.info("ReporterAgent generando informe ejecutivo final")
        return self._model.invoke([
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=(
                f"Consolidá los siguientes {len(reports)} informes de migración "
                f"en un informe ejecutivo final:\n\n{payload}"
            )),
        ]).text
