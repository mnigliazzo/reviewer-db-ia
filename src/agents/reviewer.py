from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..llm import resilient
from ..models import ReviewOutput, SqlScript
from ..skill_middleware import build_skills_header, load_skills_from_disk, make_load_skill_tool
from .base import load_prompt

_FINALIZE_INSTRUCTION = (
    "Con todo lo revisado, devolvé ahora el review como objeto estructurado "
    "(seguridad, rendimiento, mantenibilidad y la lista de hallazgos). "
    "Si no hay hallazgos válidos, devolvé la lista vacía."
)


class ReviewerAgent:

    def __init__(self, model: BaseChatModel, skills_base_path: Path, retries: int = 0):
        self._skills = load_skills_from_disk(skills_base_path)
        self.load_skill_tool = make_load_skill_tool(self._skills)
        self.model_with_tools = resilient(model.bind_tools([self.load_skill_tool]), retries)
        self._structured = resilient(model.with_structured_output(ReviewOutput), retries)
        self._system_prompt = load_prompt("reviewer_system.md") + build_skills_header(self._skills)

    def build_messages(
        self,
        script: SqlScript,
        sql_content: str,
        schema_context: str = "",
    ) -> list:
        parts = [
            f"Revisa el siguiente script de SQL Server.\n"
            f"Migracion: {script.migration} | Archivo: {script.file.name}\n",
        ]
        if schema_context:
            parts.append(f"{schema_context}\n")
        parts.append(
            f"{sql_content}\n\n"
            "Cargá las skills necesarias con load_skill() y revisá el script. "
            "Cuando termines de cargar skills, se te pedirá el review estructurado."
        )

        return [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content="\n".join(parts)),
        ]

    def finalize(self, messages: list) -> ReviewOutput:
        """Segunda fase: pide el review como objeto estructurado (sin tools)."""
        result = self._structured.invoke(
            messages + [HumanMessage(content=_FINALIZE_INSTRUCTION)]
        )
        if not isinstance(result, ReviewOutput):
            # algunos providers devuelven dict si el schema no se respeta del todo
            result = ReviewOutput.model_validate(result)
        return result
