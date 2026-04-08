from dataclasses import dataclass
from pathlib import Path


@dataclass
class SqlScript:
    migration: str      # ej: "20260407112400"
    file: Path
    is_rollback: bool


@dataclass
class ScriptReview:
    script: SqlScript
    review: str
    attempts: int           # cuántos intentos necesitó (1 = aprobado al primer intento)
    has_critical: bool
