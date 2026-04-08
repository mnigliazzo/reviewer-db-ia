"""
Memoria acumulativa del esquema SQL entre scripts.

Extrae objetos creados/modificados de cada script (tablas, SPs, vistas, índices)
y los pasa como contexto al próximo script para evitar falsos positivos
y ayudar al revisor a entender la estructura global de la migración.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SchemaMemory:
    tables:     list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)
    views:      list[str] = field(default_factory=list)
    indexes:    list[str] = field(default_factory=list)
    functions:  list[str] = field(default_factory=list)

    # Extrae nombres del patrón: CREATE [OR ALTER] <TYPE> [IF NOT EXISTS] <name>
    _PATTERNS: dict[str, re.Pattern] = field(default_factory=lambda: {
        "tables":     re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\[?[\w\.\[\]]+\]?)", re.IGNORECASE),
        "procedures": re.compile(r"CREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+(\[?[\w\.\[\]]+\]?)", re.IGNORECASE),
        "views":      re.compile(r"CREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+(\[?[\w\.\[\]]+\]?)", re.IGNORECASE),
        "indexes":    re.compile(r"CREATE\s+(?:UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?INDEX\s+(\[?[\w\.\[\]]+\]?)", re.IGNORECASE),
        "functions":  re.compile(r"CREATE\s+(?:OR\s+ALTER\s+)?FUNCTION\s+(\[?[\w\.\[\]]+\]?)", re.IGNORECASE),
    }, repr=False)

    def ingest(self, sql: str) -> None:
        """Parsea el SQL y agrega los objetos encontrados a la memoria."""
        for attr, pattern in self._PATTERNS.items():
            found = pattern.findall(sql)
            getattr(self, attr).extend(found)

    def is_empty(self) -> bool:
        return not any([self.tables, self.procedures, self.views, self.indexes, self.functions])

    def to_context_string(self) -> str:
        """
        Genera el bloque de contexto que se inyecta en el prompt del revisor.
        Permite entender el esquema acumulado de scripts anteriores.
        """
        if self.is_empty():
            return ""

        lines = ["CONTEXTO DEL ESQUEMA (objetos definidos en scripts anteriores de esta migracion):"]
        if self.tables:
            lines.append(f"  Tablas:              {', '.join(self.tables)}")
        if self.procedures:
            lines.append(f"  Stored Procedures:   {', '.join(self.procedures)}")
        if self.views:
            lines.append(f"  Vistas:              {', '.join(self.views)}")
        if self.indexes:
            lines.append(f"  Índices:             {', '.join(self.indexes)}")
        if self.functions:
            lines.append(f"  Funciones:           {', '.join(self.functions)}")
        lines.append(
            "  Tener en cuenta este contexto para evitar falsos positivos\n"
            "  (ej: no reportar como faltante algo ya definido en scripts anteriores)."
        )
        return "\n".join(lines)
