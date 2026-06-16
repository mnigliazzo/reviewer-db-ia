from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class Finding(BaseModel):
    prioridad: str   # CRÍTICO | ALTO | MEDIO | BAJO | MEJORA | OBSERVACION
    categoria: str
    skill: str
    titulo: str
    ubicacion: str = ""
    riesgo: str = ""
    recomendacion: str = ""


class ReviewResult(BaseModel):
    skills_utilizadas: list[str] = Field(default_factory=list)
    seguridad: Optional[int] = None
    rendimiento: Optional[int] = None
    mantenibilidad: Optional[int] = None
    hallazgos: list[Finding] = Field(default_factory=list)
    raw_text: str = ""

    @property
    def has_critical(self) -> bool:
        return any(f.prioridad == "CRÍTICO" for f in self.hallazgos)

    def to_text(self) -> str:
        return self.raw_text


@dataclass
class SqlScript:
    migration: str
    file: Path
    is_rollback: bool


@dataclass
class ScriptReview:
    script: SqlScript
    result: ReviewResult

    @property
    def skills_used(self) -> list[str]:
        return self.result.skills_utilizadas


# ── Parser ────────────────────────────────────────────────────────────────────

_HEADER_RE = re.compile(
    r"\s*\[(CRÍTICO|ALTO|MEDIO|BAJO|MEJORA|OBSERVACION)\]\s*"
    r"\[([^\]]+)\]\s*\[([^\]]+)\]:\s*(.+)",
    re.IGNORECASE,
)
_SCORE_RE = re.compile(r"(Seguridad|Rendimiento|Mantenibilidad):\s+(\d+)/10", re.IGNORECASE)


def _extract_field(lines: list[str], name: str) -> str:
    prefix = f"{name}:"
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def parse_review_text(text: str, skills_used: list[str]) -> ReviewResult:
    scores: dict[str, int] = {}
    for m in _SCORE_RE.finditer(text):
        scores[m.group(1).lower()] = int(m.group(2))

    hallazgos: list[Finding] = []
    section_match = re.search(r"HALLAZGOS\s*\n(.*?)$", text, re.DOTALL)
    if section_match and "Sin hallazgos" not in section_match.group(1):
        for block in re.split(r"\n\s*\n", section_match.group(1).strip()):
            lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
            if not lines:
                continue
            m = _HEADER_RE.match(lines[0])
            if not m:
                continue
            prioridad, categoria, skill, titulo = m.groups()
            hallazgos.append(Finding(
                prioridad=prioridad.upper(),
                categoria=categoria.strip(),
                skill=skill.strip(),
                titulo=titulo.strip(),
                ubicacion=_extract_field(lines[1:], "Ubicacion"),
                riesgo=_extract_field(lines[1:], "Riesgo"),
                recomendacion=_extract_field(lines[1:], "Recomendacion"),
            ))

    return ReviewResult(
        skills_utilizadas=skills_used,
        seguridad=scores.get("seguridad"),
        rendimiento=scores.get("rendimiento"),
        mantenibilidad=scores.get("mantenibilidad"),
        hallazgos=hallazgos,
        raw_text=text,
    )
