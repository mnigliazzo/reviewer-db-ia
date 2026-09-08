import pytest
from pydantic import ValidationError

from src.models import Finding, ReviewOutput, ReviewResult, format_review


def _finding(**kw):
    base = dict(prioridad="MEDIO", categoria="Rendimiento", skill="sql-optimization", titulo="t")
    base.update(kw)
    return Finding(**base)


def test_prioridad_must_be_in_the_literal_set():
    with pytest.raises(ValidationError):
        _finding(prioridad="ALTA")   # no existe, la válida es ALTO
    assert _finding(prioridad="CRÍTICO").prioridad == "CRÍTICO"


def test_scores_bounded_0_10():
    ReviewOutput(seguridad=0, rendimiento=10, mantenibilidad=5)
    with pytest.raises(ValidationError):
        ReviewOutput(seguridad=11, rendimiento=5, mantenibilidad=5)
    with pytest.raises(ValidationError):
        ReviewOutput(seguridad=-1, rendimiento=5, mantenibilidad=5)


def test_from_output_merges_skills():
    out = ReviewOutput(seguridad=7, rendimiento=7, mantenibilidad=7, hallazgos=[_finding()])
    res = ReviewResult.from_output(out, ["sql-code-review", "sql-optimization"])
    assert res.skills_utilizadas == ["sql-code-review", "sql-optimization"]
    assert res.seguridad == 7
    assert len(res.hallazgos) == 1


def test_has_critical():
    assert ReviewResult(seguridad=1, rendimiento=1, mantenibilidad=1,
                        hallazgos=[_finding(prioridad="CRÍTICO")]).has_critical is True
    assert ReviewResult(seguridad=9, rendimiento=9, mantenibilidad=9).has_critical is False


def test_format_review_no_findings():
    txt = format_review(ReviewResult(seguridad=9, rendimiento=8, mantenibilidad=7))
    assert "9/10" in txt and "Sin hallazgos." in txt


def test_format_review_with_findings():
    res = ReviewResult(
        seguridad=4, rendimiento=5, mantenibilidad=6,
        hallazgos=[_finding(prioridad="ALTO", titulo="Falta indice", ubicacion="JOIN", linea=30,
                            riesgo="scan", recomendacion="crear indice")],
    )
    txt = format_review(res)
    assert "[ALTO] [Rendimiento] [sql-optimization]: Falta indice" in txt
    assert "línea 30" in txt
    assert "Riesgo: scan" in txt
