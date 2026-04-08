from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from ..skill_middleware import build_skills_header, load_skills_from_disk, make_load_skill_tool

if TYPE_CHECKING:
    from ..main import SqlScript

logger = logging.getLogger(__name__)


class ReviewerAgent:
    """
    Agente revisor de código SQL Server / T-SQL.

    Modo actual: simple — inyecta todas las skills en el system prompt.

    Migración a modo agente (progressive disclosure):
      1. Cambiar _build_system_prompt() para usar build_skills_header()
      2. Pasar self._load_skill_tool a create_react_agent de LangGraph
      3. El agente llamará load_skill() on-demand según lo que necesite
    """

    _SYSTEM_PROMPT_BASE = (
        "Eres un DBA experto en SQL Server y revisor de código T-SQL.\n"
        "Tu tarea es revisar scripts SQL y dar feedback estructurado y accionable.\n"
        "IMPORTANTE: Responde siempre en castellano.\n"
        "IMPORTANTE: Nunca uses formato Markdown. Esto significa:\n"
        "  - Sin # o ## o ### o #### para títulos\n"
        "  - Sin ** o * para negrita o itálica\n"
        "  - Sin backticks o ``` para bloques de código\n"
        "  - Sin > para citas ni --- como separadores\n"
        "Usá MAYÚSCULAS para títulos de sección e indentación con espacios.\n\n"
        "Usá exactamente este formato:\n\n"
        "RESUMEN\n"
        "  Seguridad:       X/10\n"
        "  Rendimiento:     X/10\n"
        "  Mantenibilidad:  X/10\n\n"
        "HALLAZGOS\n\n"
        "  [PRIORIDAD] [CATEGORIA]: Titulo del hallazgo\n"
        "  Ubicacion: ...\n"
        "  Riesgo: ...\n"
        "  Recomendacion: ...\n\n"
    )

    def __init__(self, model: ChatOllama, skills_base_path: Path):
        self._model = model
        self._skills = load_skills_from_disk(str(skills_base_path))
        self._load_skill_tool = make_load_skill_tool(self._skills)  # listo para modo agente
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        skills_content = "\n\n---\n\n".join(
            f"Skill: {s['name']}\n\n{s['content']}" for s in self._skills
        )
        return self._SYSTEM_PROMPT_BASE + "Guías de revisión:\n\n" + skills_content

    def review(self, script: SqlScript, validator_feedback: str | None = None) -> str:
        """
        Revisa el script SQL.
        Si validator_feedback está presente, es un reintento: el validador
        detectó problemas en el review anterior y pide que se corrijan.
        """
        sql_content = script.file.read_text(encoding="utf-8")
        script_type = "ROLLBACK" if script.is_rollback else "FORWARD MIGRATION"

        user_content = (
            f"Revisa el siguiente script de SQL Server.\n"
            f"Migracion: {script.migration} | Tipo: {script_type} | Archivo: {script.file.name}\n\n"
            f"{sql_content}\n\n"
            "Responde UNICAMENTE en texto plano sin ningun simbolo Markdown. "
            "Usa el formato indicado en las instrucciones del sistema."
        )

        if validator_feedback:
            user_content += (
                f"\n\nATENCION - REINTENTO: El review anterior fue rechazado por el validador.\n"
                f"Feedback a corregir:\n{validator_feedback}\n"
                "Por favor, corrige estos puntos en el nuevo review."
            )

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=user_content),
        ]

        logger.debug(f"ReviewerAgent invocando modelo para {script.file.name}")
        return self._model.invoke(messages).content
