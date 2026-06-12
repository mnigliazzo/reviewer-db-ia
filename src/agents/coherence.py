from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from .reviewer import _load_prompt

logger = logging.getLogger(__name__)


@dataclass
class CoherenceResult:
    report: str
    approved: bool   # False si hay operaciones forward sin revertir


class CoherenceAgent:
    """
    Agente de coherencia de migración.

    Dado el conjunto completo de scripts forward y rollback de una migración,
    genera:
      1. Resumen legible de qué hace el despliegue (forward)
      2. Resumen legible de qué hace el rollback
      3. Análisis de coherencia: ¿el rollback revierte todo lo que hizo el forward?

    Se ejecuta una vez por migración, después de que todos los scripts
    individuales fueron revisados.
    """

    def __init__(self, model: BaseChatModel):
        self._model = model
        self._system_prompt = _load_prompt("coherence_system.md")

    def analyze(
        self,
        migration: str,
        forward_scripts: list[tuple[str, str]],   # [(nombre_archivo, contenido), ...]
        rollback_scripts: list[tuple[str, str]],
    ) -> CoherenceResult:
        """
        Analiza la coherencia entre forward y rollback de una migración.

        Args:
            migration: nombre/id de la migración (ej: "20260407112400")
            forward_scripts: lista de (nombre_archivo, contenido_sql) de scripts forward
            rollback_scripts: lista de (nombre_archivo, contenido_sql) de scripts rollback
        """
        if not forward_scripts:
            report = (
                f"MIGRACION: {migration}\n\n"
                "No hay scripts de despliegue forward para analizar."
            )
            return CoherenceResult(report=report, approved=True)

        forward_block = "\n\n".join(
            f"--- {name} ---\n{content}" for name, content in forward_scripts
        )

        if rollback_scripts:
            rollback_block = "\n\n".join(
                f"--- {name} ---\n{content}" for name, content in rollback_scripts
            )
        else:
            rollback_block = "(No se encontraron scripts de rollback para esta migración)"

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(
                content=(
                    f"Analiza la siguiente migración: {migration}\n\n"
                    f"=== SCRIPTS DE DESPLIEGUE (FORWARD) ===\n\n"
                    f"{forward_block}\n\n"
                    f"=== SCRIPTS DE ROLLBACK ===\n\n"
                    f"{rollback_block}"
                )
            ),
        ]

        logger.info(f"CoherenceAgent analizando migración {migration} "
                    f"({len(forward_scripts)} forward, {len(rollback_scripts)} rollback)")

        response = self._model.invoke(messages).content
        approved = "RESULTADO: COHERENTE" in response.upper()

        return CoherenceResult(report=response, approved=approved)
