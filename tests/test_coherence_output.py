import pytest
from pydantic import ValidationError

from src.models import CoherenceOutput, Veredicto


def test_veredicto_coherente_aprueba():
    out = CoherenceOutput(veredicto="COHERENTE")
    assert out.veredicto is Veredicto.COHERENTE
    assert out.approved is True


def test_veredicto_incompleto_no_aprueba():
    assert CoherenceOutput(veredicto="INCOMPLETO").approved is False


def test_default_es_incompleto():
    # el modelo no devolvió veredicto -> no aprobado por omisión (fail-safe)
    assert CoherenceOutput().veredicto is Veredicto.INCOMPLETO
    assert CoherenceOutput().approved is False


def test_veredicto_fuera_del_enum_es_validation_error():
    # sin leniencia en Python: un veredicto no canónico revienta el schema.
    # El ValidationError sube desde coherence_node y aborta la corrida.
    for bad in ("coherente", "", "COHERENTE PARCIALMENTE"):
        with pytest.raises(ValidationError):
            CoherenceOutput(veredicto=bad)


def test_render_incluye_secciones_y_resultado():
    out = CoherenceOutput(
        resumen_forward="CREATE TABLE Foo",
        resumen_rollback="DROP TABLE Foo",
        analisis_coherencia="CREATE TABLE Foo -> DROP TABLE Foo: revierte",
        veredicto="COHERENTE",
    )
    txt = out.render()
    assert "DESPLIEGUE (FORWARD)" in txt
    assert "CREATE TABLE Foo" in txt
    assert "RESULTADO: COHERENTE" in txt


def test_render_lista_operaciones_sin_revertir():
    out = CoherenceOutput(
        veredicto="INCOMPLETO",
        operaciones_sin_revertir=["ALTER TABLE Foo ADD COLUMN Bar", "CREATE INDEX IX_Foo"],
    )
    txt = out.render()
    assert "RESULTADO: INCOMPLETO" in txt
    assert "Operaciones sin revertir:" in txt
    assert "  - ALTER TABLE Foo ADD COLUMN Bar" in txt


def test_render_sin_datos_usa_placeholder():
    txt = CoherenceOutput().render()
    assert txt.count("Sin informacion.") == 3
    assert "RESULTADO: INCOMPLETO" in txt
