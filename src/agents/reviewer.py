from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from ..models import ReviewOutput, ReviewResult, SqlScript
from ..skills import load_skills, skill_calls
from .base import build_skill_agent


class ReviewerAgent:
    """Revisa un script SQL: carga las skills que necesite y devuelve un
    ``ReviewResult`` estructurado."""

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
            system_prompt_file="reviewer_system.md",
            response_format=ReviewOutput,
            max_skill_calls=max_skill_calls,
            retries=retries,
        )

    def review(
        self,
        script: SqlScript,
        sql_content: str,
        schema_context: str = "",
    ) -> ReviewResult:
        prompt = (
            f"Revisa el siguiente script de SQL Server.\n"
            f"Migracion: {script.migration} | Archivo: {script.file.name}\n"
        )
        if schema_context:
            prompt += f"\n{schema_context}\n"
        prompt += f"\n{sql_content}"

        result = self._agent.invoke({"messages": [HumanMessage(content=prompt)]})
        return ReviewResult.from_output(
            result["structured_response"], skill_calls(result["messages"])
        )
