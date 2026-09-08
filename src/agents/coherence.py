from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from ..models import CoherenceOutput
from ..skills import load_skills
from .base import build_skill_agent


class CoherenceAgent:
    """Decide si el rollback de una migración revierte todo lo que hace el
    forward. Carga las skills que necesite y devuelve un ``CoherenceOutput``
    estructurado. Se ejecuta una vez por migración."""

    def __init__(
        self,
        model: BaseChatModel,
        skills_base_path: Path,
        *,
        max_skill_calls: int = 0,
        retries: int = 0,
    ):
        self._agent = build_skill_agent(
            model,
            load_skills(skills_base_path),
            system_prompt_file="coherence_system.md",
            response_format=CoherenceOutput,
            max_skill_calls=max_skill_calls,
            retries=retries,
        )

    def analyze(
        self,
        migration: str,
        forward_scripts: list[tuple[str, str]],   # [(nombre_archivo, contenido), ...]
        rollback_scripts: list[tuple[str, str]],
    ) -> CoherenceOutput:
        forward_block = "\n\n".join(f"--- {name} ---\n{content}" for name, content in forward_scripts)
        rollback_block = "\n\n".join(
            f"--- {name} ---\n{content}" for name, content in rollback_scripts
        ) or "(No se encontraron scripts de rollback para esta migración)"

        prompt = (
            f"Analiza la coherencia de la migración: {migration}\n\n"
            f"=== SCRIPTS DE DESPLIEGUE (FORWARD) ===\n\n{forward_block}\n\n"
            f"=== SCRIPTS DE ROLLBACK ===\n\n{rollback_block}"
        )
        result = self._agent.invoke({"messages": [HumanMessage(content=prompt)]})
        return result["structured_response"]
