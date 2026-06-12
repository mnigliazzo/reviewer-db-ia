import re
from pathlib import Path
from typing import TypedDict

from langchain_core.tools import tool


class Skill(TypedDict):
    name: str
    description: str
    content: str


def load_skills_from_disk(base_path: str) -> list[Skill]:
    skills: list[Skill] = []
    path = Path(base_path)
    frontmatter_re = re.compile(r'^---\s*\n(.*?)\n---\s*\n(.*)', re.DOTALL | re.MULTILINE)

    for skill_dir in sorted(path.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        raw_text = skill_file.read_text(encoding="utf-8")
        match = frontmatter_re.match(raw_text)
        if not match:
            continue

        meta_data = {}
        for line in match.group(1).split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                meta_data[k.strip()] = v.strip().strip("'").strip('"')

        skills.append({
            "name": meta_data.get("name", skill_dir.name),
            "description": meta_data.get("description", ""),
            "content": match.group(2).strip(),
        })

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
    available = ", ".join(skill_map.keys())

    @tool
    def load_skill(skill_name: str) -> str:
        """Carga el contenido completo de una skill de revisión SQL.

        Llamar esta herramienta cuando necesites las guías detalladas
        de una skill específica antes de revisar el código SQL.

        Args:
            skill_name: Nombre de la skill a cargar, ej: "sql-code-review"
        """
        if skill_name in skill_map:
            return f"Skill cargada: {skill_name}\n\n{skill_map[skill_name]}"
        return f"Skill '{skill_name}' no encontrada. Disponibles: {available}"

    return load_skill
