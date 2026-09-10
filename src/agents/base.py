from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import Runnable

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
) -> tuple[Runnable, Runnable, SystemMessage]:
    """Dos fases, compartidas por ``ReviewerAgent`` y ``CoherenceAgent``:

    1. ``agent`` — ``create_agent`` con la tool ``load_skill`` (loop ReAct del
       framework) para que el modelo cargue las guías que necesite.
    2. ``structured`` — ``model.with_structured_output(response_format)``: una
       llamada forzada que devuelve el schema. ``create_agent`` con
       ``response_format`` no sirve con ChatOllama: corta el loop apenas el modelo
       responde sin tool calls y ``structured_response`` queda ``None`` (visto con
       ``gemma4:e4b`` y con ``qwen2.5:14b``).

    Devuelve ``(agent, structured, system_message)``. El retry lo hace el modelo
    (``max_retries``) + el ``RetryPolicy`` del grafo; el loop de tool calls lo acota
    ``recursion_limit`` — sin middleware.
    """
    system_prompt = f"{load_prompt(system_prompt_file)}\n\n{skills_header(skills)}"
    agent = create_agent(
        model,
        tools=[make_load_skill_tool(skills)],
        system_prompt=system_prompt,
    )
    return agent, model.with_structured_output(response_format), SystemMessage(content=system_prompt)
