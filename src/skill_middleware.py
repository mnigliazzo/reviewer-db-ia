from langchain.agents.middleware import ModelRequest, ModelResponse, AgentMiddleware
from langchain.messages import SystemMessage
from typing import Callable
from langchain.tools import tool


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
    
    # Regex para capturar el bloque entre --- y el resto del contenido
    frontmatter_re = re.compile(r'^---\s*\n(.*?)\n---\s*\n(.*)', re.DOTALL | re.MULTILINE)

    for skill_dir in path.iterdir():
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            raw_text = skill_file.read_text(encoding="utf-8")
            match = frontmatter_re.match(raw_text)
            
            if match:
                # Extraer metadatos (YAML-like)
                meta_block = match.group(1)
                content_block = match.group(2)
                
                # Parsear campos simples
                meta_data = {}
                for line in meta_block.split('\n'):
                    if ':' in line:
                        k, v = line.split(':', 1)
                        meta_data[k.strip()] = v.strip().strip("'").strip('"')

                skills.append({
                    "name": meta_data.get("name", skill_dir.name),
                    "description": meta_data.get("description", ""),
                    "content": content_block.strip()
                })
    return skills

# Carga inicial
SKILLS = load_skills_from_disk("src/skills")

@tool
def load_skill(skill_name: str) -> str:
    """Load the full content of a skill into the agent's context.

    Use this when you need detailed information about how to handle a specific
    type of request. This will provide you with comprehensive instructions,
    policies, and guidelines for the skill area.

    Args:
        skill_name: The name of the skill to load (e.g., "expense_reporting", "travel_booking")
    """
    # Find and return the requested skill
    for skill in SKILLS:
        if skill["name"] == skill_name:
            return f"Loaded skill: {skill_name}\n\n{skill['content']}"

    # Skill not found
    available = ", ".join(s["name"] for s in SKILLS)
    return f"Skill '{skill_name}' not found. Available skills: {available}"

class SkillMiddleware(AgentMiddleware):
    """Middleware that injects skill descriptions into the system prompt."""

    # Register the load_skill tool as a class variable
    tools = [load_skill]

    def __init__(self):
        """Initialize and generate the skills prompt from SKILLS."""
        # Build skills prompt from the SKILLS list
        skills_list = []
        for skill in SKILLS:
            skills_list.append(
                f"- **{skill['name']}**: {skill['description']}"
            )
        self.skills_prompt = "\n".join(skills_list)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync: Inject skill descriptions into system prompt."""
        # Build the skills addendum
        skills_addendum = (
            f"\n\n## Available Skills\n\n{self.skills_prompt}\n\n"
            "Use the load_skill tool when you need detailed information "
            "about handling a specific type of request."
        )

        # Append to system message content blocks
        new_content = list(request.system_message.content_blocks) + [
            {"type": "text", "text": skills_addendum}
        ]
        new_system_message = SystemMessage(content=new_content)
        modified_request = request.override(system_message=new_system_message)
        return handler(modified_request)