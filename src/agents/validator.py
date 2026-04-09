from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..models import SqlScript

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r'^\.{2,}$|^-$|^n/a$|^$', re.IGNORECASE)
_SCORE_PATTERN = re.compile(r'\b\d+(?:\.\d+)?/10\b')
_FINDING_HEADER = re.compile(r'^\s*\[[^\]]+\]\s*\[[^\]]+\]')
_PROHIBITED_FINDING_TITLE = re.compile(
    # Comentarios / documentación
    r'comentari[oa]s?|documentaci[oó]n'
    # "no se utilizan parámetros (en las inserciones / para los valores)"
    r'|no\s+se\s+utilizan\s+par[aá]metros?'
    # "uso de valores fijos/literales en INSERT"
    r'|valores?\s+(?:fijo|literal|constante)',
    re.IGNORECASE,
)


def sanitize_prohibited_findings(review: str) -> str:
    """
    Elimina del review los bloques de hallazgo cuyo título contiene
    temas que están en la lista PROHIBIDO REPORTAR (comentarios, etc.)
    independientemente de lo que haya generado el modelo.
    """
    lines = review.split('\n')
    result: list[str] = []
    skip_mode = False

    for line in lines:
        if _FINDING_HEADER.match(line):
            skip_mode = bool(_PROHIBITED_FINDING_TITLE.search(line))
            if skip_mode:
                logger.debug(f"Sanitizer: eliminando hallazgo prohibido → {line.strip()}")
        if not skip_mode:
            result.append(line)

    return '\n'.join(result)


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

        # Criterio 2 excepción: review sin hallazgos declarado explícitamente
        if re.search(r'Sin hallazgos', review, re.IGNORECASE):
            return ValidationResult(approved=True, feedback="")

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
