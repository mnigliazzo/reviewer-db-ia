from pathlib import Path

from src.main import decide_exit
from src.models import Finding, ReviewResult, ScriptReview, SqlScript


def _sr(*prioridades: str) -> ScriptReview:
    findings = [
        Finding(prioridad=p, categoria="c", skill="-", titulo=f"h {i}")
        for i, p in enumerate(prioridades)
    ]
    return ScriptReview(
        script=SqlScript("m", Path("m/001.sql"), is_rollback=False),
        result=ReviewResult(seguridad=5, rendimiento=5, mantenibilidad=5, hallazgos=findings),
    )


def test_clean_run():
    code, reasons = decide_exit([_sr("BAJO", "MEJORA")], [], {"CRÍTICO"})
    assert code == 0
    assert reasons == []


def test_critico_blocks_with_default_policy():
    code, reasons = decide_exit([_sr("CRÍTICO")], [], {"CRÍTICO"})
    assert code == 1
    assert any("bloquean" in r for r in reasons)


def test_alto_does_not_block_by_default():
    code, _ = decide_exit([_sr("ALTO")], [], {"CRÍTICO"})
    assert code == 0


def test_alto_blocks_when_in_policy():
    code, _ = decide_exit([_sr("ALTO")], [], {"CRÍTICO", "ALTO"})
    assert code == 1


def test_incomplete_rollback_always_blocks():
    code, reasons = decide_exit([_sr("BAJO")], ["20260101000000"], {"CRÍTICO"})
    assert code == 1
    assert any("INCOMPLETO" in r for r in reasons)
