from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..models import ScriptReview
from .reviewer import _load_prompt

logger = logging.getLogger(__name__)


class MiniReporterAgent:
    """
    Genera el informe por migración combinando métricas calculadas desde los
    hallazgos estructurados (Python) con un resumen narrativo del LLM.
    """

    def __init__(self, model: BaseChatModel):
        self._model = model
        self._system_prompt = _load_prompt("mini_reporter_system.md")

    def report(
        self,
        migration_id: str,
        reviews: list[ScriptReview],
        coherence_report: str,
        coherence_approved: bool,
    ) -> str:
        # ── Métricas desde datos estructurados ────────────────────────────────
        seg   = [r.result.seguridad      for r in reviews if r.result.seguridad      is not None]
        rend  = [r.result.rendimiento    for r in reviews if r.result.rendimiento    is not None]
        mant  = [r.result.mantenibilidad for r in reviews if r.result.mantenibilidad is not None]

        def avg(scores: list[int]) -> str:
            return f"{sum(scores) / len(scores):.1f}" if scores else "N/A"

        critical_high = [
            f"[{f.prioridad}] {r.script.file.name}: {f.titulo}"
            for r in reviews
            for f in r.result.hallazgos
            if f.prioridad in ("CRÍTICO", "ALTO")
        ]

        # ── Resumen narrativo vía LLM ──────────────────────────────────────────
        context = "\n\n".join(
            f"--- {r.script.file.name} ---\n{r.result.to_text()}" for r in reviews
        )
        if coherence_report:
            context += f"\n\n=== COHERENCIA ===\n{coherence_report}"

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=f"Migración: {migration_id}\n\n{context}"),
        ]
        logger.info(f"MiniReporterAgent generando informe para migración {migration_id}")
        executive_summary = self._model.invoke(messages).content.strip()

        # ── Ensamblar informe ──────────────────────────────────────────────────
        lines = [
            "ESTADISTICAS",
            f"  Scripts revisados:        {len(reviews)}",
            f"  Promedio Seguridad:       {avg(seg)}/10",
            f"  Promedio Rendimiento:     {avg(rend)}/10",
            f"  Promedio Mantenibilidad:  {avg(mant)}/10",
            "",
            f"ESTADO ROLLBACK: {'COHERENTE' if coherence_approved else 'INCOMPLETO'}",
            "",
            "HALLAZGOS CRITICOS Y ALTOS",
        ]
        lines += [f"  {h}" for h in critical_high] if critical_high else ["  Ninguno"]
        lines += ["", "RESUMEN EJECUTIVO", f"  {executive_summary}"]

        return "\n".join(lines)
