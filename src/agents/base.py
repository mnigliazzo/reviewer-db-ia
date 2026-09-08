from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel

from ..skills import Skill, make_load_skill_tool, skills_header

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    """Carga un prompt de texto plano desde ``src/prompts/``.

    Devuelve el contenido con un salto de línea doble al final para poder
    concatenarle secciones generadas (ej: el header de skills).
    """
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").rstrip() + "\n\n"


def build_skill_agent(
    model: BaseChatModel,
    skills: list[Skill],
    *,
    system_prompt_file: str,
    response_format: type,
    max_skill_calls: int,
    retries: int,
):
    """Agente ``create_agent`` de dos fases: carga skills con ``load_skill`` y
    devuelve ``response_format`` como salida estructurada.

    Lo comparten ``ReviewerAgent`` y ``CoherenceAgent``; sólo cambian el prompt
    de sistema y el schema de salida.
    """
    middleware = []
    if retries > 0:
        middleware.append(ModelRetryMiddleware(max_retries=retries))
    if max_skill_calls > 0:
        middleware.append(ToolCallLimitMiddleware(
            tool_name="load_skill",
            thread_limit=max_skill_calls,
            exit_behavior="continue",
        ))
    return create_agent(
        model,
        tools=[make_load_skill_tool(skills)],
        system_prompt=load_prompt(system_prompt_file) + skills_header(skills),
        response_format=response_format,
        middleware=middleware,
    )
