from pathlib import Path

from src.models import Finding, ReviewResult, ScriptReview, SqlScript
from src.sarif import to_sarif


def _review(root: Path, name: str, findings: list[Finding]) -> ScriptReview:
    f = root / "2026" / "20260101000000" / name
    script = SqlScript("20260101000000", f, is_rollback=False)
    return ScriptReview(script=script, result=ReviewResult(
        seguridad=5, rendimiento=5, mantenibilidad=5, hallazgos=findings,
    ))


def _f(prioridad: str, **kw) -> Finding:
    base = {
        "prioridad": prioridad, "categoria": "Seguridad", "skill": "sql-code-review",
        "titulo": "t", "riesgo": "r", "recomendacion": "fix",
    }
    base.update(kw)
    return Finding(**base)


def test_envelope(tmp_path):
    doc = to_sarif([], [], tmp_path)
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "reviewer-db-ia"
    assert doc["runs"][0]["results"] == []


def test_finding_becomes_result_with_relative_uri_and_line(tmp_path):
    sr = _review(tmp_path, "001.Foo.sql", [_f("CRÍTICO", linea=12, riesgo="r", recomendacion="fix")])
    doc = to_sarif([sr], [], tmp_path)
    res = doc["runs"][0]["results"]
    assert len(res) == 1
    loc = res[0]["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "2026/20260101000000/001.Foo.sql"
    assert loc["region"]["startLine"] == 12
    assert res[0]["level"] == "error"
    assert "Riesgo: r" in res[0]["message"]["text"]


def test_level_mapping(tmp_path):
    sr = _review(tmp_path, "x.sql", [
        _f("CRÍTICO"), _f("ALTO"), _f("MEDIO"), _f("BAJO"), _f("MEJORA"), _f("OBSERVACION"),
    ])
    levels = [r["level"] for r in to_sarif([sr], [], tmp_path)["runs"][0]["results"]]
    assert levels == ["error", "error", "warning", "warning", "note", "note"]


def test_missing_line_defaults_to_1(tmp_path):
    sr = _review(tmp_path, "x.sql", [_f("BAJO")])
    res = to_sarif([sr], [], tmp_path)["runs"][0]["results"][0]
    assert res["locations"][0]["physicalLocation"]["region"]["startLine"] == 1


def test_incoherent_migration_adds_error_result(tmp_path):
    doc = to_sarif([], ["20260101000000"], tmp_path)
    res = doc["runs"][0]["results"]
    assert len(res) == 1
    assert res[0]["ruleId"] == "rollback/incompleto"
    assert res[0]["level"] == "error"


def test_rules_are_deduplicated(tmp_path):
    sr = _review(tmp_path, "x.sql", [_f("CRÍTICO"), _f("ALTO")])  # misma skill/categoria
    rules = to_sarif([sr], [], tmp_path)["runs"][0]["tool"]["driver"]["rules"]
    assert [r["id"] for r in rules] == ["sql-code-review/Seguridad"]
