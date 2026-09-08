from __future__ import annotations

from pathlib import Path

from .models import Finding, Prioridad, ScriptReview

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)
TOOL_NAME = "reviewer-db-ia"


def _rule_id(f: Finding) -> str:
    skill, cat = f.skill.strip(), f.categoria.strip()
    return f"{skill}/{cat}" if skill and skill != "-" else cat


def _rel_uri(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _finding_result(f: Finding, uri: str) -> dict:
    text = f"{f.titulo}\nRiesgo: {f.riesgo}\nRecomendación: {f.recomendacion}"
    if f.ubicacion:
        text += f"\nUbicación: {f.ubicacion}"

    region = {"startLine": f.linea if f.linea and f.linea > 0 else 1}
    return {
        "ruleId": _rule_id(f),
        "level": f.prioridad.sarif_level,
        "message": {"text": text},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": uri},
                "region": region,
            }
        }],
        "properties": {"prioridad": f.prioridad.value, "skill": f.skill, "categoria": f.categoria},
    }


def _incoherent_result(migration_id: str) -> dict:
    return {
        "ruleId": "rollback/incompleto",
        "level": "error",
        "message": {"text": (
            f"El rollback de la migración {migration_id} no revierte todas las "
            f"operaciones del forward."
        )},
        "locations": [{
            "physicalLocation": {"artifactLocation": {"uri": f"{migration_id}/"}}
        }],
        "properties": {"prioridad": Prioridad.CRITICO.value, "categoria": "Rollback"},
    }


def to_sarif(
    all_reviews: list[ScriptReview],
    incoherent_migrations: list[str],
    scripts_root: Path,
) -> dict:
    """Construye un documento SARIF 2.1.0 con los hallazgos del pipeline."""
    results: list[dict] = []
    rule_ids: dict[str, None] = {}

    for review in all_reviews:
        uri = _rel_uri(review.script.file, scripts_root)
        for f in review.result.hallazgos:
            results.append(_finding_result(f, uri))
            rule_ids.setdefault(_rule_id(f), None)

    for migration_id in incoherent_migrations:
        results.append(_incoherent_result(migration_id))
        rule_ids.setdefault("rollback/incompleto", None)

    rules = [{"id": rid, "name": rid} for rid in rule_ids]

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {"driver": {"name": TOOL_NAME, "rules": rules}},
            "results": results,
        }],
    }
