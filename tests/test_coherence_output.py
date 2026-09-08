from src.models import CoherenceOutput, format_coherence


def test_veredicto_coherente_aprueba():
    assert CoherenceOutput(veredicto="COHERENTE").approved is True


def test_veredicto_incompleto_no_aprueba():
    assert CoherenceOutput(veredicto="INCOMPLETO").approved is False


def test_veredicto_normaliza_variantes():
    assert CoherenceOutput(veredicto="coherente").approved is True
    assert CoherenceOutput(veredicto="  COHERENTE  ").approved is True
    # cualquier cosa que no sea exactamente COHERENTE -> INCOMPLETO (fail-safe)
    assert CoherenceOutput(veredicto="COHERENTE PARCIALMENTE").veredicto == "INCOMPLETO"
    assert CoherenceOutput(veredicto="").veredicto == "INCOMPLETO"
    assert CoherenceOutput(veredicto=None).veredicto == "INCOMPLETO"


def test_default_es_incompleto():
    # el modelo no devolvió veredicto -> no aprobado por omisión
    assert CoherenceOutput().approved is False


def test_format_coherence_incluye_secciones_y_resultado():
    out = CoherenceOutput(
        resumen_forward="CREATE TABLE Foo",
        resumen_rollback="DROP TABLE Foo",
        analisis_coherencia="CREATE TABLE Foo -> DROP TABLE Foo: revierte",
        veredicto="COHERENTE",
    )
    txt = format_coherence(out)
    assert "DESPLIEGUE (FORWARD)" in txt
    assert "CREATE TABLE Foo" in txt
    assert "RESULTADO: COHERENTE" in txt


def test_format_coherence_lista_operaciones_sin_revertir():
    out = CoherenceOutput(
        veredicto="INCOMPLETO",
        operaciones_sin_revertir=["ALTER TABLE Foo ADD COLUMN Bar", "CREATE INDEX IX_Foo"],
    )
    txt = format_coherence(out)
    assert "RESULTADO: INCOMPLETO" in txt
    assert "Operaciones sin revertir:" in txt
    assert "  - ALTER TABLE Foo ADD COLUMN Bar" in txt


def test_format_coherence_sin_datos_usa_placeholder():
    txt = format_coherence(CoherenceOutput())
    assert txt.count("Sin informacion.") == 3
    assert "RESULTADO: INCOMPLETO" in txt
