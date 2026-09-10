# reviewer-db-ia

Auditor de scripts de migración SQL Server (T-SQL) con un pipeline multi-agente
(LangGraph). Pensado para correr en CI: sale con código distinto de cero si
encuentra hallazgos a partir de la severidad de `--fail-on` (default `CRÍTICO`) o un
rollback incompleto. Puede emitir un reporte SARIF 2.1.0 (`--sarif` / `REVIEWER_SARIF`)
para ver los hallazgos inline en el diff del MR.

## Estructura de scripts esperada

```
<scripts-path>/
  <AÑO>/
    <CARPETA_MIGRACION>/
      001.LoQueSea.sql
      rollback/
        001.LoQueSea.sql
```

## Puesta en marcha

```bash
cp .env.example .env      # y completá PROVIDER / MODEL_* / SCRIPTS_PATH
```

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
make install                                    # = uv pip install -e .  (Windows: .\make.ps1 install)
python run.py
```

`make.ps1` es el equivalente del `Makefile` para Windows (mismos targets:
`install` / `build` / `run` / `clean` / …), no necesita `make` ni bash.

`run.py` es el entrypoint (cualquier plataforma; re-ejecuta con el python del `.venv`
si hace falta). Lee de `.env` / `.env.local` (`.env.local` pisa a `.env`):
`PROVIDER`, `MODEL_BASE_URL`, `MODEL_AGENT`, `SCRIPTS_PATH`, `LOG_LEVEL`,
`REVIEWER_MAX_*`, `REVIEWER_FAIL_ON`, `REVIEWER_LLM_TIMEOUT`, `REVIEWER_LLM_RETRIES`,
`REVIEWER_SARIF`, `API_KEY` y `SKIP_REPORTER`. Una variable no vacía ya definida en el
entorno tiene prioridad. En `.env` los comentarios van en su propia línea (no al final
de una línea de valor). Para invocar el CLI a mano: `python -m src.main --help`.

### Pipeline completo con delta (`make run`)

`make run` clona `db-scripts`, lo recorta hasta `current_db_version.txt` y revisa
solo el delta nuevo. Corre en dos modos, según `MODE` en `.env` (default `docker`):

```bash
make build                 # solo para MODE=docker
make run                   # MODE del .env
make run MODE=local        # el CLI corre en el venv local (via run.py), sin contenedor
make run MODE=docker       # el CLI corre dentro del contenedor
make clean
```

En Windows es lo mismo con `.\make.ps1`: `.\make.ps1 run`, `.\make.ps1 run -Mode local`, etc.

`make` lee la configuración de `.env`. `MODE=local` necesita el venv con deps
(`make install`).

## Tests

```bash
uv pip install -e ".[dev]"
pytest
```
