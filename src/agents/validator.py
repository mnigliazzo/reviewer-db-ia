from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..models import SqlScript

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r'^\.{2,}$|^-$|^n/a$|^$', re.IGNORECASE)
_SCORE_PATTERN = re.compile(r'\b\d+(?:\.\d+)?/10\b')


def _is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER.match(text.strip()))


@dataclass
class ValidationResult:
    approved: bool
    feedback: str


class ValidatorAgent:
    """
    Valida la estructura del review producido por el ReviewerAgent.

    Criterios (todos estructurales, sin LLM):
      1. El RESUMEN contiene al menos 3 puntuaciones X/10
      2. Al menos un hallazgo tiene Ubicacion, Riesgo y Recomendacion con
         contenido real (no '...', no vacío)
    """

    def validate(self, script: SqlScript, review: str) -> ValidationResult:
        # Criterio 1: al menos 3 puntuaciones X/10 en el review
        scores = _SCORE_PATTERN.findall(review)
        if len(scores) < 3:
            return ValidationResult(
                approved=False,
                feedback=(
                    "Motivo: El RESUMEN no tiene las 3 puntuaciones X/10.\n"
                    "Correccion requerida: Incluir RESUMEN con "
                    "Seguridad: X/10, Rendimiento: X/10, Mantenibilidad: X/10."
                ),
            )

        # Criterio 2: al menos un hallazgo con los 3 campos con contenido real
        ubicacion = re.search(r'Ubicacion[:\s]+(.+)', review, re.IGNORECASE)
        riesgo    = re.search(r'Riesgo[:\s]+(.+)',    review, re.IGNORECASE)
        recomend  = re.search(r'Recomendacion[:\s]+(.+)', review, re.IGNORECASE)

        missing = []
        for field, match in [("Ubicacion", ubicacion), ("Riesgo", riesgo), ("Recomendacion", recomend)]:
            if not match or _is_placeholder(match.group(1)):
                missing.append(field)

        if missing:
            return ValidationResult(
                approved=False,
                feedback=(
                    f"Motivo: Los campos {', '.join(missing)} están vacíos o son '...'.\n"
                    "Correccion requerida: Completar esos campos con contenido real y específico."
                ),
            )

        logger.debug(f"ValidatorAgent: review de {script.file.name} aprobado estructuralmente")
        return ValidationResult(approved=True, feedback="")
