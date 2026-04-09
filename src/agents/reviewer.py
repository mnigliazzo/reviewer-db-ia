from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ..models import SqlScript
from ..skill_middleware import build_skills_header, load_skills_from_disk, make_load_skill_tool

logger = logging.getLogger(__name__)

ReviewResult = tuple[str, list[str]]

MAX_TOOL_ROUNDS = 5     # máximo de rondas de tool calling antes de cortar

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    """Carga un prompt desde src/prompts/ y normaliza el trailing whitespace."""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").rstrip() + "\n\n"


class ReviewerAgent:
    """
    Agente revisor con progressive disclosure.

    Flujo:
      1. El system prompt muestra solo nombre + descripción de cada skill.
      2. El modelo llama load_skill() para las skills que necesita.
      3. Se ejecuta un loop manual de tool calling (bind_tools).
      4. Si el modelo no llamó ninguna tool (modelo pequeño / CPU),
         se hace fallback inyectando todas las skills directamente.
    """

    def __init__(self, model: BaseChatModel, skills_base_path: Path):
        self._skills = load_skills_from_disk(str(skills_base_path))
        self._load_skill_tool = make_load_skill_tool(self._skills)
        self._model_with_tools = model.bind_tools([self._load_skill_tool])
        self._model = model

        system_base   = _load_prompt("reviewer_system.md")
        fallback_base = _load_prompt("reviewer_fallback.md")

        # Prompt con progressive disclosure (solo descripciones de skills)
        self._system_prompt = system_base + build_skills_header(self._skills)

        # Prompt de fallback con todas las skills inyectadas
        skills_content = "\n\n---\n\n".join(
            f"Skill: {s['name']}\n\n{s['content']}" for s in self._skills
        )
        self._fallback_prompt = fallback_base + skills_content

    def review(
        self,
        script: SqlScript,
        validator_feedback: str | None = None,
        schema_context: str = "",
    ) -> ReviewResult:
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

        user_content = "\n".join(parts)

        # --- Loop manual de tool calling ---
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=user_content),
        ]
        skills_used: list[str] = []

        try:
            for round_num in range(MAX_TOOL_ROUNDS):
                response = self._model_with_tools.invoke(messages)
                messages.append(response)

                if not getattr(response, "tool_calls", None):
                    break   # el modelo terminó de razonar

                for tc in response.tool_calls:
                    tool_result = self._load_skill_tool.invoke(tc["args"])
                    skill_name = tc["args"].get("skill_name", "")
                    if skill_name and skill_name not in skills_used:
                        skills_used.append(skill_name)
                    messages.append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))
        except Exception as e:
            if "tool_use_failed" in str(e) or "Failed to call a function" in str(e):
                logger.warning(
                    f"El modelo no soporta tool calling correctamente ({type(e).__name__}). "
                    "Aplicando fallback con skills inyectadas directamente."
                )
                skills_used = []   # fuerza el fallback de abajo
            else:
                raise

        # --- Fallback si el modelo no usó ningún tool ---
        if not skills_used:
            logger.warning(
                "El modelo no llamó a load_skill() (modelo pequeño o CPU). "
                "Aplicando fallback con skills inyectadas directamente."
            )
            fallback_messages = [
                SystemMessage(content=self._fallback_prompt),
                HumanMessage(content=user_content),
            ]
            response = self._model.invoke(fallback_messages)

        logger.info(
            f"  Skills usadas: {', '.join(skills_used)}"
            if skills_used else "  Skills usadas: fallback (todas inyectadas)"
        )

        return response.content, skills_used
