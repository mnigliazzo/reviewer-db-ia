from dataclasses import dataclass
from pathlib import Path


@dataclass
class SqlScript:
    migration: str
    file: Path
    is_rollback: bool


@dataclass
class ScriptReview:
    script: SqlScript
    review: str
    skills_used: list[str]
