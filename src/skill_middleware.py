import re
from pathlib import Path
from typing import List, TypedDict


class Skill(TypedDict):
    name: str
    description: str
    content: str


def load_skills_from_disk(base_path: str) -> List[Skill]:
    skills = []
    path = Path(base_path)

    # Captura el bloque de frontmatter entre --- y el resto del contenido
    frontmatter_re = re.compile(r'^---\s*\n(.*?)\n---\s*\n(.*)', re.DOTALL | re.MULTILINE)

    for skill_dir in path.iterdir():
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
