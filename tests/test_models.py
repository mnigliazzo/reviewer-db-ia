from src.models import Finding, ReviewOutput, ReviewResult, format_review


def _finding(**kw):
    base = dict(prioridad="MEDIO", categoria="Rendimiento", skill="sql-optimization", titulo="t")
    base.update(kw)
    return Finding(**base)


def test_prioridad_normaliza_variantes():
    assert _finding(prioridad="ALTA").prioridad == "ALTO"
    assert _finding(prioridad="media").prioridad == "MEDIO"
    assert _finding(prioridad="HIGH").prioridad == "ALTO"
    assert _finding(prioridad="CRÍTICO").prioridad == "CRÍTICO"
    # cualquier cosa desconocida -> OBSERVACION, sin romper
    assert _finding(prioridad="wat").prioridad == "OBSERVACION"


def test_finding_campos_opcionales():
    # el modelo devolvió un hallazgo a medias: no debe explotar
    f = Finding.model_validate({"prioridad": "MEDIO", "categoria": ""})
    assert f.skill == "-"
    assert f.titulo == ""
    assert f.is_empty is True


def test_scores_se_clampean():
    assert ReviewOutput(seguridad=11, rendimiento=-3, mantenibilidad=5).seguridad == 10
    assert ReviewOutput(seguridad=11, rendimiento=-3, mantenibilidad=5).rendimiento == 0
    assert ReviewOutput(seguridad="8", rendimiento="x", mantenibilidad=7).rendimiento == 5  # no numérico -> 5


def test_from_output_merges_skills_y_descarta_vacios():
    out = ReviewOutput(
        seguridad=7, rendimiento=7, mantenibilidad=7,
        hallazgos=[_finding(), Finding.model_validate({"prioridad": "BAJO"})],  # 2do vacío
    )
    res = ReviewResult.from_output(out, ["sql-code-review", "sql-optimization"])
    assert res.skills_utilizadas == ["sql-code-review", "sql-optimization"]
    assert res.seguridad == 7
    assert len(res.hallazgos) == 1   # el hallazgo vacío se descartó


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
