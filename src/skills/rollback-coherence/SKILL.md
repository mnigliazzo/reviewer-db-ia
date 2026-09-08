---
name: rollback-coherence
description: 'Criterios para evaluar si el rollback de una migración SQL Server revierte por completo el script forward: contrapartes DDL/DML esperadas (CREATE/DROP, ADD/DROP COLUMN, INSERT/DELETE), semántica de DROP TABLE, orden de reversión y qué casos cuentan como INCOMPLETO.'
---

# Coherencia forward / rollback

Objetivo: determinar si el rollback deshace TODAS las operaciones del forward y
deja la base en el estado previo a la migración.

## Contrapartes esperadas

| Operación del forward | Rollback esperado |
| --- | --- |
| `CREATE TABLE` | `DROP TABLE` |
| `ALTER TABLE ... ADD COLUMN` | `ALTER TABLE ... DROP COLUMN` |
| `ALTER TABLE ... ADD CONSTRAINT` | `ALTER TABLE ... DROP CONSTRAINT` |
| `CREATE INDEX` | `DROP INDEX` |
| `CREATE PROCEDURE` / `VIEW` / `FUNCTION` / `TRIGGER` | `DROP` del mismo objeto |
| `INSERT` de datos nuevos | `DELETE` de esos datos (o `TRUNCATE` si la tabla queda vacía) |
| `UPDATE` de datos existentes | `UPDATE` que restaura los valores previos |
| `EXEC sp_rename` | `EXEC sp_rename` inverso |
| `DROP` de un objeto | recrearlo con su definición original |

## Reglas

- `DROP TABLE` elimina la tabla Y todos sus datos implícitamente. Si el forward
  hace `CREATE TABLE` + `INSERT` y el rollback hace `DROP TABLE`, es COHERENTE:
  no se requiere un `DELETE` explícito adicional.
- El `DROP` de una tabla también se lleva sus índices, constraints y triggers
  definidos sobre ella; no hace falta un `DROP` individual de cada uno.
- El rollback debe respetar las dependencias: revertir en orden inverso al
  forward (FKs, objetos que referencian a otros).
- Un `UPDATE` o `DELETE` sobre filas preexistentes sólo es reversible si el
  rollback reconstruye los valores originales. Si no los guarda ni los
  reconstruye, la operación queda sin revertir → INCOMPLETO.
- Objeto creado en un script anterior de la MISMA migración y usado en este: no
  es un hueco de este rollback.

## Veredicto

- COHERENTE: cada operación del forward tiene su contraparte y el estado
  resultante es equivalente al previo a la migración.
- INCOMPLETO: queda al menos una operación del forward sin revertir, no hay
  scripts de rollback, o no se puede verificar con certeza. Listar en
  `operaciones_sin_revertir` cada hueco concreto (con el nombre real del objeto).
