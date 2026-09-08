from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from ..skills import Skill, make_load_skill_tool, skills_header

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    """Carga un prompt de texto plano desde ``src/prompts/`` (sin espacios al borde)."""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def build_skill_agent(
    model: BaseChatModel,
    skills: list[Skill],
    *,
    system_prompt_file: str,
    response_format: type,
):
    """Agente ``create_agent`` de dos fases: carga skills con ``load_skill`` y
    devuelve ``response_format`` como salida estructurada.

    Lo comparten ``ReviewerAgent`` y ``CoherenceAgent``; sólo cambian el prompt de
    sistema y el schema de salida. El retry lo hace el modelo (``max_retries``) y el
    loop de tool calls lo acota el ``recursion_limit`` de langgraph — sin middleware.
    """
    system_prompt = f"{load_prompt(system_prompt_file)}\n\n{skills_header(skills)}"
    return create_agent(
        model,
        tools=[make_load_skill_tool(skills)],
        system_prompt=system_prompt,
        response_format=response_format,
    )
