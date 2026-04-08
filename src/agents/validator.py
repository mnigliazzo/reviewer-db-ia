from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

if TYPE_CHECKING:
    from ..main import SqlScript

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    approved: bool
    feedback: str


class ValidatorAgent:
    """
    Agente validador: evalúa la calidad del review producido por el ReviewerAgent.

    Criterios de aprobación:
      - Incluye scores de seguridad, rendimiento y mantenibilidad
      - Tiene al menos un hallazgo con ubicación, riesgo y recomendación específica
      - Las recomendaciones mencionan objetos SQL concretos (tablas, columnas, SPs)
      - No es superficial ni genérico

    Si el review no cumple, retorna el feedback específico para que el
    ReviewerAgent lo corrija en un reintento.
    """

    _SYSTEM_PROMPT = (
        "Eres un revisor de calidad de análisis de código SQL.\n"
        "Tu tarea es evaluar si el review de código SQL producido por otro agente\n"
        "es suficientemente completo, específico y accionable.\n"
        "IMPORTANTE: Responde siempre en castellano.\n"
        "IMPORTANTE: Nunca uses formato Markdown.\n\n"
        "Criterios de aprobación (todos deben cumplirse):\n"
        "  1. Incluye puntuaciones numéricas (X/10) para seguridad, rendimiento y mantenibilidad\n"
        "  2. Tiene al menos un hallazgo con ubicacion, riesgo y recomendacion\n"
        "  3. Las recomendaciones son específicas: mencionan objetos SQL concretos\n"
        "     (nombres de tablas, columnas, stored procedures, índices, etc.)\n"
        "  4. No es un review genérico que podría aplicarse a cualquier script\n\n"
        "Responde UNICAMENTE con uno de estos dos formatos:\n\n"
        "APROBADO\n\n"
        "o bien:\n\n"
        "RECHAZADO\n"
        "Motivo: [explicacion concreta de qué falta o es incorrecto]\n"
        "Correccion requerida: [instruccion precisa de qué debe mejorar el revisor]\n"
    )

    def __init__(self, model: ChatOllama):
        self._model = model

    def validate(self, script: SqlScript, review: str) -> ValidationResult:
        """
        Valida el review de un script SQL.
        Retorna ValidationResult con approved=True/False y feedback si fue rechazado.
        """
        messages = [
            SystemMessage(content=self._SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Evalúa el siguiente review del script '{script.file.name}'.\n\n"
                    f"REVIEW A EVALUAR:\n{review}"
                )
            ),
        ]

        logger.debug(f"ValidatorAgent evaluando review de {script.file.name}")
        response = self._model.invoke(messages).content.strip()

        if response.upper().startswith("APROBADO"):
            return ValidationResult(approved=True, feedback="")

        # Extraer el feedback del rechazo
        feedback = response.replace("RECHAZADO", "").strip()
        return ValidationResult(approved=False, feedback=feedback)
