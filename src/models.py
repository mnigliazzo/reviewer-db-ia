from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# Prioridades válidas de un hallazgo, en orden de severidad descendente.
PRIORIDADES = ("CRÍTICO", "ALTO", "MEDIO", "BAJO", "MEJORA", "OBSERVACION")
Prioridad = Literal["CRÍTICO", "ALTO", "MEDIO", "BAJO", "MEJORA", "OBSERVACION"]


class Finding(BaseModel):
    """Un hallazgo del review. Es parte del schema de salida estructurada del LLM."""

    prioridad: Prioridad = Field(description="Severidad del hallazgo")
    categoria: str = Field(description="Categoría corta, ej: Seguridad, Rendimiento, Integridad")
    skill: str = Field(description="Nombre de la skill que aplicaste para detectarlo, o '-'")
    titulo: str = Field(description="Título breve del hallazgo")
    ubicacion: str = Field(default="", description="Dónde en el script (texto libre)")
    linea: int | None = Field(default=None, description="Número de línea, o null si no aplica")
    riesgo: str = Field(default="", description="Qué puede salir mal")
    recomendacion: str = Field(default="", description="Cómo corregirlo")


class ReviewOutput(BaseModel):
    """Schema que el ReviewerAgent le pide al LLM vía ``with_structured_output``."""

    seguridad: int = Field(ge=0, le=10, description="Puntaje de seguridad 0-10")
    rendimiento: int = Field(ge=0, le=10, description="Puntaje de rendimiento 0-10")
    mantenibilidad: int = Field(ge=0, le=10, description="Puntaje de mantenibilidad 0-10")
    hallazgos: list[Finding] = Field(default_factory=list)


class ReviewResult(ReviewOutput):
    """``ReviewOutput`` + los datos que agrega el pipeline (no los pone el LLM)."""

    skills_utilizadas: list[str] = Field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(f.prioridad == "CRÍTICO" for f in self.hallazgos)

    @classmethod
    def from_output(cls, output: ReviewOutput, skills_utilizadas: list[str]) -> ReviewResult:
        return cls(**output.model_dump(), skills_utilizadas=skills_utilizadas)


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


def format_review(result: ReviewResult) -> str:
    """Render legible de un ``ReviewResult`` para logs y para el contexto del
    MiniReporterAgent (reemplaza al viejo ``raw_text``)."""
    lines = [
        f"Seguridad: {result.seguridad}/10   "
        f"Rendimiento: {result.rendimiento}/10   "
        f"Mantenibilidad: {result.mantenibilidad}/10",
        "",
    ]
    if not result.hallazgos:
        lines.append("Sin hallazgos.")
        return "\n".join(lines)

    for f in result.hallazgos:
        loc = f.ubicacion or ""
        if f.linea is not None:
            loc = f"{loc} (línea {f.linea})".strip()
        lines.append(f"[{f.prioridad}] [{f.categoria}] [{f.skill}]: {f.titulo}")
        if loc:
            lines.append(f"  Ubicacion: {loc}")
        if f.riesgo:
            lines.append(f"  Riesgo: {f.riesgo}")
        if f.recomendacion:
            lines.append(f"  Recomendacion: {f.recomendacion}")
        lines.append("")
    return "\n".join(lines).rstrip()
