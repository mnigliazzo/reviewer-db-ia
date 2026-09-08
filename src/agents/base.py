from __future__ import annotations

from pathlib import Path

from langchain_core.messages import BaseMessage

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    """Carga un prompt de texto plano desde ``src/prompts/``.

    Devuelve el contenido con un salto de línea doble al final para poder
    concatenarle secciones generadas (ej: el header de skills).
    """
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").rstrip() + "\n\n"


def message_text(response: object) -> str:
    """Normaliza el ``content`` de una respuesta del LLM a ``str``.

    Los providers OpenAI-compatibles pueden devolver ``content`` como una lista
    de bloques (``[{"type": "text", "text": "..."}, ...]``) en vez de un string
    plano. Esta función acepta un ``BaseMessage``, un string, o una lista de
    bloques y siempre devuelve texto.
    """
    content = response.content if isinstance(response, BaseMessage) else response

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "".join(parts)
    return str(content)
