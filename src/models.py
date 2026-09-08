from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field


class Prioridad(StrEnum):
    """Severidad de un hallazgo, en orden descendente.

    Es el enum del schema de salida estructurada: el LLM debe devolver
    exactamente uno de estos valores. Un valor fuera del set es un
    ``ValidationError`` — no se normaliza ni se mapea nada en Python.
    """

    CRITICO = "CRÍTICO"
    ALTO = "ALTO"
    MEDIO = "MEDIO"
    BAJO = "BAJO"
    MEJORA = "MEJORA"
    OBSERVACION = "OBSERVACION"

    @property
    def sarif_level(self) -> str:
        return _SARIF_LEVEL[self]


_SARIF_LEVEL = {
    Prioridad.CRITICO: "error",
    Prioridad.ALTO: "error",
    Prioridad.MEDIO: "warning",
    Prioridad.BAJO: "warning",
    Prioridad.MEJORA: "note",
    Prioridad.OBSERVACION: "note",
}


class Veredicto(StrEnum):
    """Resultado del análisis de coherencia forward / rollback."""

    COHERENTE = "COHERENTE"
    INCOMPLETO = "INCOMPLETO"


class Finding(BaseModel):
    """Un hallazgo del review. Parte del schema de salida estructurada del LLM."""

    prioridad: Prioridad = Field(description="Severidad del hallazgo")
    categoria: str = Field(default="general", description="Categoría corta, ej: Seguridad, Rendimiento")
    skill: str = Field(default="-", description="Nombre de la skill que lo detectó, o '-'")
    titulo: str = Field(min_length=1, description="Título breve del hallazgo")
    ubicacion: str = Field(default="", description="Dónde en el script (texto libre)")
    linea: int | None = Field(default=None, description="Número de línea, o null si no aplica")
    riesgo: str = Field(min_length=1, description="Qué puede salir mal")
    recomendacion: str = Field(min_length=1, description="Cómo corregirlo")

    def render(self) -> str:
        loc = self.ubicacion
        if self.linea is not None:
            loc = f"{loc} (línea {self.linea})".strip()
        lineas = [f"[{self.prioridad}] [{self.categoria}] [{self.skill}]: {self.titulo}"]
        if loc:
            lineas.append(f"  Ubicacion: {loc}")
        lineas.append(f"  Riesgo: {self.riesgo}")
        lineas.append(f"  Recomendacion: {self.recomendacion}")
        return "\n".join(lineas)


class ReviewOutput(BaseModel):
    """Schema que el ReviewerAgent le pide al LLM vía ``with_structured_output``."""

    seguridad: int = Field(ge=0, le=10, description="Puntaje de seguridad 0-10")
    rendimiento: int = Field(ge=0, le=10, description="Puntaje de rendimiento 0-10")
    mantenibilidad: int = Field(ge=0, le=10, description="Puntaje de mantenibilidad 0-10")
    hallazgos: list[Finding] = Field(default_factory=list)


class ReviewResult(ReviewOutput):
    """``ReviewOutput`` + los datos que agrega el pipeline (no los pone el LLM)."""

    skills_utilizadas: list[str] = Field(default_factory=list)

    @classmethod
    def from_output(cls, output: ReviewOutput, skills_utilizadas: list[str]) -> ReviewResult:
        return cls(**output.model_dump(), skills_utilizadas=skills_utilizadas)

    def render(self) -> str:
        """Render legible para logs y para el contexto del MiniReporterAgent."""
        cabecera = (
            f"Seguridad: {self.seguridad}/10   "
            f"Rendimiento: {self.rendimiento}/10   "
            f"Mantenibilidad: {self.mantenibilidad}/10"
        )
        if not self.hallazgos:
            return f"{cabecera}\n\nSin hallazgos."
        return f"{cabecera}\n\n" + "\n\n".join(h.render() for h in self.hallazgos)


class CoherenceOutput(BaseModel):
    """Schema que el CoherenceAgent le pide al LLM vía ``with_structured_output``.

    ``veredicto`` es un enum estricto: sin normalización ni alias. Un valor fuera
    del set es un ``ValidationError`` que sube desde ``coherence_node`` y aborta la
    corrida (sin red de seguridad). El default ``INCOMPLETO`` sí se mantiene: un
    modelo que omite el campo no aprueba por omisión. Que el modelo devuelva la
    palabra exacta es responsabilidad de la skill ``rollback-coherence``.
    """

    resumen_forward: str = Field(
        default="",
        description="Qué crea, modifica o elimina cada script de despliegue (forward), con nombres reales de objetos",
    )
    resumen_rollback: str = Field(
        default="",
        description="Qué elimina, revierte o restaura cada script de rollback",
    )
    analisis_coherencia: str = Field(
        default="",
        description="Operación por operación: si cada cambio del forward tiene su contraparte en el rollback",
    )
    veredicto: Veredicto = Field(
        default=Veredicto.INCOMPLETO,
        description='EXACTAMENTE "COHERENTE" o "INCOMPLETO"',
    )
    operaciones_sin_revertir: list[str] = Field(
        default_factory=list,
        description="Operaciones del forward que el rollback no revierte (vacía si es COHERENTE)",
    )

    @property
    def approved(self) -> bool:
        return self.veredicto is Veredicto.COHERENTE

    def render(self) -> str:
        """Render legible para logs y para el contexto del MiniReporterAgent."""
        lineas = [
            "DESPLIEGUE (FORWARD)",
            f"  {self.resumen_forward or 'Sin informacion.'}",
            "",
            "ROLLBACK",
            f"  {self.resumen_rollback or 'Sin informacion.'}",
            "",
            "COHERENCIA",
            f"  {self.analisis_coherencia or 'Sin informacion.'}",
            "",
            f"RESULTADO: {self.veredicto}",
        ]
        if self.operaciones_sin_revertir:
            lineas.append("Operaciones sin revertir:")
            lineas += [f"  - {op}" for op in self.operaciones_sin_revertir]
        return "\n".join(lineas)


@dataclass
class SqlScript:
    migration: str
    file: Path
    is_rollback: bool


@dataclass
class ScriptReview:
    script: SqlScript
    result: ReviewResult


@dataclass
class MigrationReport:
    """Informe de una migración: métricas calculadas en Python desde los hallazgos
    estructurados + el resumen narrativo del LLM. No es un schema de salida del LLM."""

    migration_id: str
    scripts_revisados: int
    prom_seguridad: float | None
    prom_rendimiento: float | None
    prom_mantenibilidad: float | None
    rollback_coherente: bool
    hallazgos_altos: list[str]        # ["[PRIORIDAD] archivo: titulo", ...]
    resumen_ejecutivo: str

    @classmethod
    def build(
        cls,
        migration_id: str,
        reviews: list[ScriptReview],
        coherence: CoherenceOutput | None,
        resumen_ejecutivo: str,
    ) -> MigrationReport:
        def promedio(attr: str) -> float | None:
            valores = [getattr(r.result, attr) for r in reviews]
            return round(float(mean(valores)), 1) if valores else None

        return cls(
            migration_id=migration_id,
            scripts_revisados=len(reviews),
            prom_seguridad=promedio("seguridad"),
            prom_rendimiento=promedio("rendimiento"),
            prom_mantenibilidad=promedio("mantenibilidad"),
            rollback_coherente=coherence.approved if coherence else True,
            hallazgos_altos=[
                f"[{f.prioridad}] {r.script.file.name}: {f.titulo}"
                for r in reviews
                for f in r.result.hallazgos
                if f.prioridad in (Prioridad.CRITICO, Prioridad.ALTO)
            ],
            resumen_ejecutivo=resumen_ejecutivo,
        )

    def render(self) -> str:
        """Layout de texto para logs y como input del informe ejecutivo final."""
        def score(v: float | None) -> str:
            return f"{v:.1f}/10" if v is not None else "N/A"

        lineas = [
            f"MIGRACIÓN {self.migration_id}",
            "",
            "ESTADISTICAS",
            f"  Scripts revisados:        {self.scripts_revisados}",
            f"  Promedio Seguridad:       {score(self.prom_seguridad)}",
            f"  Promedio Rendimiento:     {score(self.prom_rendimiento)}",
            f"  Promedio Mantenibilidad:  {score(self.prom_mantenibilidad)}",
            "",
            f"ESTADO ROLLBACK: {'COHERENTE' if self.rollback_coherente else 'INCOMPLETO'}",
            "",
            "HALLAZGOS CRITICOS Y ALTOS",
            *([f"  {h}" for h in self.hallazgos_altos] or ["  Ninguno"]),
            "",
            "RESUMEN EJECUTIVO",
            f"  {self.resumen_ejecutivo}",
        ]
        return "\n".join(lineas)
