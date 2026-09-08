from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TypedDict

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


class Skill(TypedDict):
    name: str
    description: str
    content: str


def _parse_frontmatter(block: str) -> dict[str, str]:
    """Parser mínimo de frontmatter YAML: solo pares ``clave: valor`` planos.

    Ignora líneas en blanco y comentarios (``#``). Suficiente para el
    frontmatter de ``SKILL.md`` (name / description).
    """
    meta: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'").strip('"')
    return meta


def load_skills_from_disk(base_path: Path | str) -> list[Skill]:
    skills: list[Skill] = []
    path = Path(base_path)

    if not path.is_dir():
        logger.warning(f"Directorio de skills inexistente: {path}")
        return skills

    for skill_dir in sorted(p for p in path.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        match = _FRONTMATTER_RE.match(skill_file.read_text(encoding="utf-8"))
        if not match:
            logger.warning(f"{skill_file} no tiene frontmatter válido — se omite")
            continue

        meta = _parse_frontmatter(match.group(1))
        skills.append({
            "name": meta.get("name", skill_dir.name),
            "description": meta.get("description", ""),
            "content": match.group(2).strip(),
        })

    logger.info(
        "Skills cargadas: %s",
        ", ".join(s["name"] for s in skills) if skills else "ninguna",
    )
    return skills


def build_skills_header(skills: list[Skill]) -> str:
    lines = ["## Skills disponibles\n"]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
    lines.append(
        "\nUsa la herramienta load_skill() para cargar el contenido "
        "completo de la skill que necesites."
    )
    return "\n".join(lines)


def make_load_skill_tool(skills: list[Skill]):
    skill_map = {s["name"]: s["content"] for s in skills}
    available = ", ".join(skill_map.keys()) or "(ninguna)"

    @tool
    def load_skill(skill_name: str) -> str:
        """Carga el contenido completo de una skill de revisión SQL.

        Llamar esta herramienta cuando necesites las guías detalladas
        de una skill específica antes de revisar el código SQL.

        Args:
            skill_name: Nombre de la skill a cargar, ej: "sql-code-review"
        """
        name = (skill_name or "").strip()
        if name in skill_map:
            return f"Skill cargada: {name}\n\n{skill_map[name]}"
        return f"Skill '{skill_name}' no encontrada. Disponibles: {available}"

    return load_skill
