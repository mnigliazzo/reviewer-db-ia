import pytest
from pydantic import ValidationError

from src.models import Finding, Prioridad, ReviewOutput, ReviewResult


def _finding(**kw):
    base = {
        "prioridad": "MEDIO", "categoria": "Rendimiento", "skill": "sql-optimization",
        "titulo": "t", "riesgo": "r", "recomendacion": "fix",
    }
    base.update(kw)
    return Finding(**base)


def test_prioridad_es_enum_estricto():
    assert _finding(prioridad="CRÍTICO").prioridad is Prioridad.CRITICO
    assert _finding(prioridad="MEDIO").prioridad == "MEDIO"          # StrEnum == str


def test_prioridad_fuera_del_set_es_error():
    # sin alias ni normalización: 'ALTA' / 'HIGH' / 'wat' revientan el schema
    for bad in ("ALTA", "HIGH", "media", "wat", ""):
        with pytest.raises(ValidationError):
            _finding(prioridad=bad)


def test_finding_campos_de_contenido_son_requeridos():
    with pytest.raises(ValidationError):
        Finding(prioridad="MEDIO", riesgo="r", recomendacion="f")      # falta titulo
    with pytest.raises(ValidationError):
        Finding(prioridad="MEDIO", titulo="t", recomendacion="f")      # falta riesgo
    with pytest.raises(ValidationError):
        Finding(prioridad="MEDIO", titulo="t", riesgo="r", recomendacion="")  # vacío


def test_scores_fuera_de_rango_son_error():
    with pytest.raises(ValidationError):
        ReviewOutput(seguridad=11, rendimiento=5, mantenibilidad=5)
    with pytest.raises(ValidationError):
        ReviewOutput(seguridad=5, rendimiento=-3, mantenibilidad=5)
    with pytest.raises(ValidationError):
        ReviewOutput(seguridad="x", rendimiento=5, mantenibilidad=5)


def test_scores_son_requeridos():
    with pytest.raises(ValidationError):
        ReviewOutput(seguridad=5, rendimiento=5)   # falta mantenibilidad


def test_from_output_mergea_skills_sin_filtrar_hallazgos():
    out = ReviewOutput(
        seguridad=7, rendimiento=7, mantenibilidad=7,
        hallazgos=[_finding(), _finding(prioridad="BAJO")],
    )
    res = ReviewResult.from_output(out, ["sql-code-review", "sql-optimization"])
    assert res.skills_utilizadas == ["sql-code-review", "sql-optimization"]
    assert res.seguridad == 7
    assert len(res.hallazgos) == 2


def test_has_critical():
    assert ReviewResult(
        seguridad=1, rendimiento=1, mantenibilidad=1,
        hallazgos=[_finding(prioridad="CRÍTICO")],
    ).has_critical is True
    assert ReviewResult(seguridad=9, rendimiento=9, mantenibilidad=9).has_critical is False


def test_render_sin_hallazgos():
    txt = ReviewResult(seguridad=9, rendimiento=8, mantenibilidad=7).render()
    assert "9/10" in txt and "Sin hallazgos." in txt


def test_render_con_hallazgos():
    res = ReviewResult(
        seguridad=4, rendimiento=5, mantenibilidad=6,
        hallazgos=[_finding(prioridad="ALTO", titulo="Falta indice", ubicacion="JOIN", linea=30,
                            riesgo="scan", recomendacion="crear indice")],
    )
    txt = res.render()
    assert "[ALTO] [Rendimiento] [sql-optimization]: Falta indice" in txt
    assert "línea 30" in txt
    assert "Riesgo: scan" in txt
