from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Prioridades válidas de un hallazgo, en orden de severidad descendente.
PRIORIDADES = ("CRÍTICO", "ALTO", "MEDIO", "BAJO", "MEJORA", "OBSERVACION")
Prioridad = Literal["CRÍTICO", "ALTO", "MEDIO", "BAJO", "MEJORA", "OBSERVACION"]

# Variantes que devuelven algunos modelos -> prioridad canónica.
_PRIORIDAD_ALIAS = {
    "CRITICO": "CRÍTICO", "CRITICA": "CRÍTICO", "CRÍTICA": "CRÍTICO", "CRITICAL": "CRÍTICO",
    "ALTA": "ALTO", "HIGH": "ALTO",
    "MEDIA": "MEDIO", "MEDIUM": "MEDIO", "MED": "MEDIO",
    "BAJA": "BAJO", "LOW": "BAJO", "MINOR": "BAJO",
    "MEJORAS": "MEJORA", "IMPROVEMENT": "MEJORA",
    "OBSERVACIÓN": "OBSERVACION", "OBSERVACIONES": "OBSERVACION",
    "INFO": "OBSERVACION", "NOTE": "OBSERVACION", "NOTA": "OBSERVACION",
}


def normalize_prioridad(value: object) -> str:
    """Mapea el valor del modelo a una prioridad canónica; default OBSERVACION."""
    s = str(value or "").strip().upper()
    if s in PRIORIDADES:
        return s
    return _PRIORIDAD_ALIAS.get(s, "OBSERVACION")


class Finding(BaseModel):
    """Un hallazgo del review. Es parte del schema de salida estructurada del LLM.

    Todos los campos tienen default y ``prioridad`` se normaliza: los modelos
    chicos a veces devuelven hallazgos a medias o con etiquetas no canónicas y
    no queremos que eso invalide el review entero.
    """

    prioridad: str = Field(
        default="OBSERVACION",
        description="Severidad: CRÍTICO | ALTO | MEDIO | BAJO | MEJORA | OBSERVACION",
        json_schema_extra={"enum": list(PRIORIDADES)},
    )
    categoria: str = Field(default="general", description="Categoría corta, ej: Seguridad, Rendimiento")
    skill: str = Field(default="-", description="Nombre de la skill que lo detectó, o '-'")
    titulo: str = Field(default="", description="Título breve del hallazgo")
    ubicacion: str = Field(default="", description="Dónde en el script (texto libre)")
    linea: int | None = Field(default=None, description="Número de línea, o null si no aplica")
    riesgo: str = Field(default="", description="Qué puede salir mal")
    recomendacion: str = Field(default="", description="Cómo corregirlo")

    @field_validator("prioridad", mode="before")
    @classmethod
    def _norm_prioridad(cls, v: object) -> str:
        return normalize_prioridad(v)

    @property
    def is_empty(self) -> bool:
        """Hallazgo sin contenido útil (el modelo lo empezó y no lo completó)."""
        return not (self.titulo.strip() or self.riesgo.strip() or self.recomendacion.strip())


class ReviewOutput(BaseModel):
    """Schema que el ReviewerAgent le pide al LLM vía ``with_structured_output``."""

    seguridad: int = Field(default=5, description="Puntaje de seguridad 0-10")
    rendimiento: int = Field(default=5, description="Puntaje de rendimiento 0-10")
    mantenibilidad: int = Field(default=5, description="Puntaje de mantenibilidad 0-10")
    hallazgos: list[Finding] = Field(default_factory=list)

    @field_validator("seguridad", "rendimiento", "mantenibilidad", mode="before")
    @classmethod
    def _clamp_score(cls, v: object) -> int:
        try:
            n = int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 5
        return max(0, min(10, n))


class ReviewResult(ReviewOutput):
    """``ReviewOutput`` + los datos que agrega el pipeline (no los pone el LLM)."""

    skills_utilizadas: list[str] = Field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(f.prioridad == "CRÍTICO" for f in self.hallazgos)

    @classmethod
    def from_output(cls, output: ReviewOutput, skills_utilizadas: list[str]) -> ReviewResult:
        return cls(
            seguridad=output.seguridad,
            rendimiento=output.rendimiento,
            mantenibilidad=output.mantenibilidad,
            hallazgos=[h for h in output.hallazgos if not h.is_empty],
            skills_utilizadas=skills_utilizadas,
        )


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
