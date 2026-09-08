from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from langchain_core.messages import AnyMessage
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n(.*)", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    content: str


def load_skills(base_path: Path | str) -> list[Skill]:
    """Carga las skills de ``<base_path>/*/SKILL.md`` (frontmatter YAML + cuerpo)."""
    path = Path(base_path)
    if not path.is_dir():
        logger.warning(f"Directorio de skills inexistente: {path}")
        return []

    skills: list[Skill] = []
    for skill_file in sorted(path.glob("*/SKILL.md")):
        match = _FRONTMATTER_RE.match(skill_file.read_text(encoding="utf-8"))
        if not match:
            logger.warning(f"{skill_file} no tiene frontmatter YAML — se omite")
            continue
        meta = yaml.safe_load(match.group(1)) or {}
        skills.append(Skill(
            name=meta.get("name", skill_file.parent.name),
            description=meta.get("description", ""),
            content=match.group(2).strip(),
        ))

    logger.info("Skills cargadas: %s", ", ".join(s.name for s in skills) or "ninguna")
    return skills


def skills_header(skills: list[Skill]) -> str:
    """Sección para el system prompt: lista nombre + descripción de cada skill."""
    lines = ["## Skills disponibles\n"]
    lines += [f"- {s.name}: {s.description}" for s in skills]
    lines.append(
        "\nUsá la herramienta load_skill() para cargar el contenido completo "
        "de la skill que necesites."
    )
    return "\n".join(lines)


def make_load_skill_tool(skills: list[Skill]):
    bodies = {s.name: s.content for s in skills}

    @tool
    def load_skill(skill_name: str) -> str:
        """Carga el contenido completo de una skill de revisión SQL.

        Args:
            skill_name: Nombre de la skill, ej: "sql-code-review".
        """
        try:
            return bodies[skill_name]
        except KeyError:
            raise ValueError(
                f"Skill '{skill_name}' no existe. Disponibles: {', '.join(bodies)}"
            ) from None

    return load_skill


def skill_calls(messages: list[AnyMessage]) -> list[str]:
    """Nombres de skills que el agente cargó, únicos y en orden de primera aparición."""
    used: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call["name"] == "load_skill":
                name = call["args"].get("skill_name")
                if name and name not in used:
                    used.append(name)
    return used
