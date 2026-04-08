from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from ..models import ScriptReview

logger = logging.getLogger(__name__)


class ReporterAgent:
    """
    Agente reportero: consolida todos los reviews individuales en un
    informe ejecutivo final con métricas y prioridades globales.

    Se ejecuta una sola vez al final, luego de que todos los scripts
    fueron revisados y validados.
    """

    _SYSTEM_PROMPT = (
        "Eres un DBA senior encargado de generar informes ejecutivos de calidad de código SQL.\n"
        "Recibirás los reviews individuales de múltiples scripts SQL y deberás consolidarlos\n"
        "en un informe ejecutivo final.\n"
        "IMPORTANTE: Responde siempre en castellano.\n"
        "IMPORTANTE: Nunca uses formato Markdown.\n"
        "Usá MAYÚSCULAS para títulos de sección e indentación con espacios.\n\n"
        "El informe debe incluir:\n\n"
        "INFORME EJECUTIVO DE CALIDAD SQL\n\n"
        "ESTADISTICAS GENERALES\n"
        "  Total de scripts revisados: N\n"
        "  Scripts con issues críticos: N\n"
        "  Promedio Seguridad:       X/10\n"
        "  Promedio Rendimiento:     X/10\n"
        "  Promedio Mantenibilidad:  X/10\n\n"
        "SCRIPTS QUE REQUIEREN ATENCION URGENTE\n"
        "  [lista de scripts con issues críticos o altos]\n\n"
        "PATRONES DE PROBLEMAS MAS FRECUENTES\n"
        "  [problemas que aparecen en múltiples scripts]\n\n"
        "RECOMENDACIONES GLOBALES\n"
        "  [acciones a tomar a nivel de proyecto o equipo]\n"
    )

    def __init__(self, model: ChatOllama):
        self._model = model

    def report(self, reviews: list[ScriptReview]) -> str:
        """Genera el informe ejecutivo consolidado."""
        if not reviews:
            return "No hay reviews para consolidar."

        reviews_text = ""
        for i, sr in enumerate(reviews, 1):
            label = f"[ROLLBACK] {sr.script.file.name}" if sr.script.is_rollback else sr.script.file.name
            reviews_text += (
                f"--- Script {i}: {sr.script.migration}/{label} "
                f"(intentos: {sr.attempts}, critico: {'SI' if sr.has_critical else 'NO'}) ---\n"
                f"{sr.review}\n\n"
            )

        messages = [
            SystemMessage(content=self._SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Consolida los siguientes {len(reviews)} reviews en un informe ejecutivo:\n\n"
                    f"{reviews_text}"
                )
            ),
        ]

        logger.info("ReporterAgent generando informe ejecutivo final")
        return self._model.invoke(messages).content
