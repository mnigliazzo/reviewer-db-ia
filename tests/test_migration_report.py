from pathlib import Path

from src.models import (
    CoherenceOutput,
    Finding,
    MigrationReport,
    ReviewResult,
    ScriptReview,
    SqlScript,
    Veredicto,
)


def _review(name: str, scores: tuple[int, int, int], *prioridades: str) -> ScriptReview:
    hallazgos = [
        Finding(prioridad=p, categoria="c", skill="-", titulo=f"h{i}", riesgo="r", recomendacion="f")
        for i, p in enumerate(prioridades)
    ]
    result = ReviewResult(
        seguridad=scores[0], rendimiento=scores[1], mantenibilidad=scores[2],
        hallazgos=hallazgos, skills_utilizadas=[],
    )
    return ScriptReview(script=SqlScript("m", Path(name), is_rollback=False), result=result)


def test_promedios_y_filtro_de_hallazgos():
    reviews = [_review("001.sql", (8, 6, 10), "ALTO", "BAJO"), _review("002.sql", (6, 6, 6), "CRÍTICO")]
    coherence = CoherenceOutput(veredicto=Veredicto.COHERENTE)

    rep = MigrationReport.build("2026/01", reviews, coherence, "resumen")

    assert rep.scripts_revisados == 2
    assert rep.prom_seguridad == 7.0
    assert rep.prom_mantenibilidad == 8.0
    assert rep.rollback_coherente is True
    assert rep.hallazgos_altos == ["[ALTO] 001.sql: h0", "[CRÍTICO] 002.sql: h0"]


def test_sin_reviews_promedios_none_y_rollback_aprobado_por_defecto():
    rep = MigrationReport.build("m", [], None, "nada")
    assert rep.prom_seguridad is None
    assert rep.rollback_coherente is True
    assert rep.hallazgos_altos == []


def test_render_incluye_secciones():
    rep = MigrationReport.build(
        "2026/01",
        [_review("001.sql", (5, 5, 5), "ALTO")],
        CoherenceOutput(veredicto=Veredicto.INCOMPLETO),
        "La migración crea Foo.",
    )
    txt = rep.render()
    assert "MIGRACIÓN 2026/01" in txt
    assert "Promedio Seguridad:       5.0/10" in txt
    assert "ESTADO ROLLBACK: INCOMPLETO" in txt
    assert "[ALTO] 001.sql: h0" in txt
    assert "La migración crea Foo." in txt


def test_render_sin_hallazgos_altos_dice_ninguno():
    rep = MigrationReport.build("m", [_review("a.sql", (9, 9, 9))], None, "ok")
    assert "  Ninguno" in rep.render()
