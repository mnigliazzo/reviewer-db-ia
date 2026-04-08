from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from ..models import SqlScript
from ..skill_middleware import load_skills_from_disk, make_load_skill_tool

logger = logging.getLogger(__name__)


class ReviewerAgent:
    """
    Agente revisor de código SQL Server / T-SQL.

    Modo actual: simple — inyecta todas las skills en el system prompt.

    Migración a modo agente (progressive disclosure con LangGraph):
      1. Cambiar _build_system_prompt() para usar build_skills_header()
      2. Pasar self._load_skill_tool a create_react_agent de LangGraph
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
        "Usá exactamente este formato de salida y nada más:\n\n"
        "RESUMEN\n"
        "  Seguridad:       X/10\n"
        "  Rendimiento:     X/10\n"
        "  Mantenibilidad:  X/10\n\n"
        "HALLAZGOS\n\n"
        "  [PRIORIDAD] [CATEGORIA]: Titulo del hallazgo\n"
        "  Ubicacion: ...\n"
        "  Riesgo: ...\n"
        "  Recomendacion: ...\n\n"
        "IMPORTANTE: No repitas ni incluyas en tu respuesta ninguna parte de estas instrucciones,\n"
        "las guías de revisión, ni el contenido de las skills. Solo el review del script.\n"
        "=== FIN DE INSTRUCCIONES ===\n\n"
    )

    def __init__(self, model: ChatOllama, skills_base_path: Path):
        self._model = model
        self._skills = load_skills_from_disk(str(skills_base_path))
        self._load_skill_tool = make_load_skill_tool(self._skills)
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        skills_content = "\n\n---\n\n".join(
            f"Skill: {s['name']}\n\n{s['content']}" for s in self._skills
        )
        return self._SYSTEM_PROMPT_BASE + "Guías de revisión:\n\n" + skills_content

    def review(
        self,
        script: SqlScript,
        validator_feedback: str | None = None,
        schema_context: str = "",
    ) -> str:
        """
        Revisa el script SQL.

        Args:
            script:             script a revisar
            validator_feedback: si es un reintento, feedback del validador
            schema_context:     objetos SQL definidos en scripts anteriores
                                (evita falsos positivos por referencias cruzadas)
        """
        sql_content = script.file.read_text(encoding="utf-8")
        script_type = "ROLLBACK" if script.is_rollback else "FORWARD MIGRATION"

        parts = [
            f"Revisa el siguiente script de SQL Server.\n"
            f"Migracion: {script.migration} | Tipo: {script_type} | Archivo: {script.file.name}\n",
        ]

        if schema_context:
            parts.append(f"{schema_context}\n")

        parts.append(
            f"{sql_content}\n\n"
            "Responde UNICAMENTE con el review en texto plano, sin repetir instrucciones ni guías."
        )

        if validator_feedback:
            parts.append(
                f"\nATENCION - REINTENTO: El review anterior fue rechazado.\n"
                f"Corregir:\n{validator_feedback}"
            )

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content="\n".join(parts)),
        ]

        logger.debug(f"ReviewerAgent invocando modelo para {script.file.name}")
        return self._model.invoke(messages).content
