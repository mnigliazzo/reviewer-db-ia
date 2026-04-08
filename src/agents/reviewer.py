from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

from ..models import SqlScript
from ..skill_middleware import build_skills_header, load_skills_from_disk, make_load_skill_tool

logger = logging.getLogger(__name__)

# Tipo de retorno del reviewer: (review_text, skills_usadas)
ReviewResult = tuple[str, list[str]]


class ReviewerAgent:
    """
    Agente revisor con progressive disclosure.

    El system prompt solo muestra nombre + descripción de cada skill.
    El agente llama load_skill() explícitamente para cargar el contenido
    completo de la skill que necesite. Esto permite:
      - Trazar exactamente qué skill generó cada hallazgo
      - Usar solo los tokens necesarios (no cargar todo siempre)
      - Atribuir hallazgos a skills específicas en el reporte final
    """

    _SYSTEM_PROMPT_BASE = (
        "Eres un DBA experto en SQL Server y revisor de código T-SQL.\n"
        "Tu tarea es revisar scripts SQL y dar feedback estructurado y accionable.\n\n"
        "ANTES de revisar cualquier script, DEBES llamar a load_skill() para cargar\n"
        "las guías de revisión que necesites. Las skills disponibles se listan abajo.\n\n"
        "IMPORTANTE: Responde siempre en castellano.\n"
        "IMPORTANTE: Nunca uses formato Markdown.\n"
        "Usá MAYÚSCULAS para títulos de sección e indentación con espacios.\n\n"
        "Formato de salida:\n\n"
        "SKILLS UTILIZADAS: skill-name-1, skill-name-2\n\n"
        "RESUMEN\n"
        "  Seguridad:       X/10\n"
        "  Rendimiento:     X/10\n"
        "  Mantenibilidad:  X/10\n\n"
        "HALLAZGOS\n\n"
        "  [PRIORIDAD] [CATEGORIA] [skill-name]: Titulo del hallazgo\n"
        "  Ubicacion: ...\n"
        "  Riesgo: ...\n"
        "  Recomendacion: ...\n\n"
        "IMPORTANTE: No repitas el contenido de las skills en tu respuesta.\n"
        "=== FIN DE INSTRUCCIONES ===\n\n"
    )

    def __init__(self, model: ChatOllama, skills_base_path: Path):
        skills = load_skills_from_disk(str(skills_base_path))
        self._load_skill_tool = make_load_skill_tool(skills)
        self._system_prompt = self._SYSTEM_PROMPT_BASE + build_skills_header(skills)
        self._agent = create_react_agent(model=model, tools=[self._load_skill_tool])

    def review(
        self,
        script: SqlScript,
        validator_feedback: str | None = None,
        schema_context: str = "",
    ) -> ReviewResult:
        """
        Revisa el script SQL usando progressive disclosure.
        Retorna (review_text, skills_usadas).
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
            "Cargá las skills necesarias con load_skill() y luego generá el review.\n"
            "Responde UNICAMENTE con el review en texto plano, sin repetir instrucciones."
        )

        if validator_feedback:
            parts.append(
                f"\nATENCION - REINTENTO: El review anterior fue rechazado.\n"
                f"Corregir:\n{validator_feedback}"
            )

        result = self._agent.invoke({
            "messages": [
                SystemMessage(content=self._system_prompt),
                HumanMessage(content="\n".join(parts)),
            ]
        })

        # Extraer skills usadas de los tool_calls del agente
        skills_used: list[str] = []
        for msg in result["messages"]:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["name"] == "load_skill":
                        skill_name = tc["args"].get("skill_name", "")
                        if skill_name and skill_name not in skills_used:
                            skills_used.append(skill_name)

        if skills_used:
            logger.info(f"  Skills cargadas: {', '.join(skills_used)}")
        else:
            logger.warning("  El agente no llamó a load_skill() — review sin guías de skill")

        final_content = result["messages"][-1].content
        return final_content, skills_used
