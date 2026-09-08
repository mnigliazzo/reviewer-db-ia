from src.agents.coherence import parse_coherence_verdict


def test_coherente():
    assert parse_coherence_verdict("PARTE 3 - COHERENCIA\n...\nRESULTADO: COHERENTE\n") is True


def test_incompleto():
    text = "RESULTADO: INCOMPLETO\nOperaciones sin revertir: [DROP TABLE Foo]\n"
    assert parse_coherence_verdict(text) is False


def test_incompleto_wins_over_coherente_mention():
    text = "El forward parece COHERENTE pero...\nRESULTADO: INCOMPLETO\n"
    assert parse_coherence_verdict(text) is False


def test_indeterminado():
    assert parse_coherence_verdict("bla bla sin linea de resultado") is None


def test_case_insensitive_and_whitespace():
    assert parse_coherence_verdict("   resultado:   coherente   ") is True


def test_partial_coherente_does_not_match():
    assert parse_coherence_verdict("RESULTADO: COHERENTE PARCIALMENTE") is None
