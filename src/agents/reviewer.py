from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..models import SqlScript
from ..skill_middleware import build_skills_header, load_skills_from_disk, make_load_skill_tool

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").rstrip() + "\n\n"


class ReviewerAgent:

    def __init__(self, model: BaseChatModel, skills_base_path: Path):
        self._skills = load_skills_from_disk(str(skills_base_path))
        self.load_skill_tool = make_load_skill_tool(self._skills)
        self.model_with_tools = model.bind_tools([self.load_skill_tool])
        self._system_prompt = _load_prompt("reviewer_system.md") + build_skills_header(self._skills)

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
            "Cargá las skills necesarias con load_skill() y luego generá el review.\n"
            "Responde UNICAMENTE con el review en texto plano, sin repetir instrucciones."
        )

        return [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content="\n".join(parts)),
        ]
