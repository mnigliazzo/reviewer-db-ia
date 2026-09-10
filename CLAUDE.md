# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CI tool that reviews SQL Server (T-SQL) database migration scripts with a multi-agent
LangGraph pipeline before they are merged. It exits non-zero when it finds findings at
or above the `--fail-on` severity (default `CRÍTICO`) or an incomplete rollback, so it
can gate a merge. All prompts, reports, log messages, and most code comments are in
Spanish — keep new user-facing strings in Spanish.

## Running it

`run.py` is the single cross-platform direct-run entrypoint (replaced the old
`run.sh` / `run.ps1` pair). It reads a whitelisted subset of keys (`PROVIDER`,
`MODEL_BASE_URL`, `MODEL_AGENT`, `SCRIPTS_PATH`, `LOG_LEVEL`, `REVIEWER_MAX_*`,
`REVIEWER_FAIL_ON`, `REVIEWER_LLM_TIMEOUT`, `REVIEWER_LLM_RETRIES`, `REVIEWER_SARIF`,
`API_KEY`, `SKIP_REPORTER`) from `.env` / `.env.local` (`.env.local` overriding
`.env`); a non-empty real env var wins over both. It re-execs itself with the repo
`.venv` python if needed and never writes to the environment. `.env.example` values
must not carry inline `# comments` — the parser doesn't strip them.

```bash
cp .env.example .env      # then fill in values
python run.py             # any platform
```

```bash
# Direct invocation (what the scripts build up)
python -m src.main --scripts-path <ROOT> --base-url <URL> --model-agent <MODEL> \
    [--provider ollama|openai|openrouter|groq] [--api-key KEY] [--skip-reporter] \
    [--max-schema-scripts N] [--log-level INFO] \
    [--temperature 0.0] [--llm-timeout 120] [--llm-retries 2] \
    [--fail-on CRÍTICO[,ALTO,...]] [--sarif PATH]
```

`--scripts-path`, `--base-url`, `--model-agent` are required. `--max-schema-scripts 0`
means *unlimited* (not "disabled"). `--fail-on` (default
`CRÍTICO`) is the CSV of prioridades that make the run exit non-zero; an incomplete
rollback always fails regardless. `--sarif PATH` writes a SARIF 2.1.0 report (the only
machine-readable output). `run.py` exposes these as `REVIEWER_FAIL_ON`,
`REVIEWER_LLM_TIMEOUT`, `REVIEWER_LLM_RETRIES`, `REVIEWER_SARIF`.

```bash
# Full pipeline
make install   # uv pip install -e .
make build     # only needed for MODE=docker
make run       # [prepare-delta ->] run-$(MODE) [-> clean-tmp]
make clean
```

`make run` dispatches on two vars, each `command-line var > <VAR>= in .env > default`,
invalid value → `$(error)`:
- **`MODE`** (`docker` default | `local`) — where the CLI runs.
  - `MODE=docker` → `docker compose run --rm reviewer`. The container's `CMD`
    (Dockerfile) is `python run.py`; `docker-compose.yml` has **no `command:`**, it only
    passes the `REVIEWER_*` / `PROVIDER` / … env vars through (and sets
    `SCRIPTS_PATH=/app/scripts_review` via Dockerfile `ENV`).
  - `MODE=local` → `python run.py` — runs in the repo `.venv`, no container.
- **`SOURCE`** (`clone` default | `folder`) — where the scripts come from.
  - `clone` → `prepare-delta` (clone + trim) before the run, `clean-tmp` after.
  - `folder` → neither; the run uses `SCRIPTS_PATH` / `REVIEW_SCRIPTS_PATH` from `.env`
    as-is. In the Makefile `PREPARE := $(if $(filter clone,$(SOURCE)),prepare-delta,)`
    is the `run` prerequisite; `make.ps1` mirrors it in `Target-Run` via `Resolve-Source`.

`run.py` is the single source of truth for the env-var → CLI-flag mapping.
`run-docker` / `run-local` are also callable directly (without the prepare-delta /
clean-tmp wrapper).

`make.ps1` is the Windows port of the `Makefile` (same targets, no `make`/bash needed).
Keep the two in sync when changing orchestration (targets, `MODE` / `SOURCE` dispatch,
the prepare-delta trim rules).
`make.ps1` is ASCII-only on purpose — Windows PowerShell 5.1 misreads a BOM-less UTF-8
script.

`make prepare-delta` shallow-clones the external `db-scripts` GitLab repo into
`./tmp/db-script`, reads `current_db_version.txt` (format `YEAR/TIMESTAMP`), and deletes
every migration folder at or below that version, leaving only the new delta for review.

Python >= 3.12; runtime deps (`langchain`, `langgraph`, `langchain-ollama`,
`langchain-openai`, `pydantic`) install via `uv pip install -e .`. Tests
(`pytest`) and the linter (`ruff`) are in the `dev` extra:
`uv pip install -e ".[dev]" && pytest`. Pure helpers are unit-tested under
`tests/`; there is no integration test that exercises a real LLM.

## Config notes

- Nothing is loaded from `.env` by `src/` itself — argparse only. `.env` is consumed by
  `run.py` (whitelisted keys), the Makefile (`ENV_FILE_NAME := .env`), and
  `docker-compose.yml` (`--env-file`). `.env*` is gitignored; `.env.example` is the only
  committed env file / template.
- GitLab CI (`-.gitlab-ci.yml` — the leading `-` in the name is intentional/odd) only
  builds and pushes the Docker image, and only on `master`.
- `.claude/` is Claude Code config, unrelated to `src/skills/` (see below).

## Architecture

### Script discovery (`src/main.py`)

`discover_scripts` walks a fixed layout:
`<scripts_path>/<YEAR>/<MIGRATION_FOLDER>/NNN.Name.sql`, plus an optional
`rollback/` subfolder inside each migration. Scripts are grouped by migration folder
name; forward and rollback files are read into memory up front and passed as
`(name, content)` tuples.

### One LangGraph graph, run with `.batch()` (`src/graph.py` + `src/main.py`)

**Migration batch** — `graph.build_migration_states` turns the migration list into one
`MigrationState` per migration that has forward scripts (a migration without any is
skipped with a warning). Each state carries its own `schema_context` = the forward
scripts of the *earlier* migrations (`build_schema_context`, capped by
`--max-schema-scripts`), which is known upfront. `main` runs them with
`migration_graph.batch(states, config={"max_concurrency": 4})` — the framework's Runnable
batch, no orchestration loop of our own. Then `ReporterAgent` runs once (unless
`--skip-reporter`). `main` derives `all_reviews` / `reports` / `incoherent` from the
result list for `decide_exit` / SARIF.

**Migration graph** (`MigrationState`, the only compiled graph) — a straight line:
`START` —(conditional `Send` fan-out, one per forward script)→ parallel `review_script`
→ `coherence` → `mini_reporter` → `END`. `coherence` runs once after the implicit fan-in
(no `gather`/join node). Parallel-worker state merges with `operator.add` reducers.
`review_script` calls `reviewer.review(...)`, `coherence` calls
`coherence_agent.analyze(...)`, `mini_reporter` calls `mini_reporter_agent.generate(...)`.
`ReviewerAgent` / `CoherenceAgent` are **two phases** (`agents/base.build_skill_agent`
returns `(agent, structured, system_message)`): **(1)** a `create_agent` ReAct loop with
the `load_skill` tool lets the model pull the guides it needs; **(2)**
`model.with_structured_output(schema)` is invoked on the resulting messages to force the
`ReviewOutput` / `CoherenceOutput` back (ollama `format=` — the model has no choice).
`create_agent`'s own `response_format` is *not* used: with ChatOllama it ends the loop
the moment the model answers without a tool call, leaving `structured_response=None`
every time (seen with `gemma4:e4b` and `qwen2.5:14b`). No hand-rolled tool loop, no text
parsing.

`review_script` and `coherence` carry a langgraph `RetryPolicy` (`_LLM_RETRY`,
`max_attempts=3`, `retry_on` = `RuntimeError` / `ValueError` / `ConnectionError` /
`TimeoutError`): if phase 2 still returns nothing or a bad schema,
`ReviewResult.from_output` / `analyze` raise, and the node is retried. **After** the
retries are exhausted there is no further safety net: the
exception propagates out of the node and aborts the whole run with a non-zero exit — no
synthetic `_REVIEW_FALLO` finding, no fail-safe not-approved. A genuine `INCOMPLETO`
veredicto still flows through normally (→ `incoherent` → exit 1 with a clean message).
`mini_reporter_node` (falls back to a placeholder `MigrationReport`) and the
`ReporterAgent` call in `main` swallow errors — the reports are informational and never
gate the merge.

### Agents (`src/agents/`)

- **`ReviewerAgent`** — reviews one script. `review(script, sql, schema_context)` runs
  the two-phase flow above and returns a `ReviewResult` (`ReviewOutput` +
  `skill_calls(messages)`). System prompt = `reviewer_system.md` + a generated skills
  header (also prepended to the phase-2 structured call).
- **`CoherenceAgent`** — runs once per migration; checks the rollback reverts the
  forward. `analyze(migration, forward, rollback)` — same two-phase shape,
  `with_structured_output(CoherenceOutput)`. The
  rollback-completeness criteria live in the `rollback-coherence` skill, not the prompt.
  `CoherenceOutput.veredicto` is the strict `Veredicto` `StrEnum` (no Python
  normalization; an off-enum value is a `ValidationError` that propagates out of
  `coherence_node` and aborts the run); `.approved` is `veredicto is Veredicto.COHERENTE`. `CoherenceOutput.render()`
  produces the report (logged + fed to the MiniReporter) from the structured fields.
- **`MiniReporterAgent`** — `generate(migration_id, reviews, coherence) -> MigrationReport`:
  one plain `model.invoke(...).text` for the narrative `resumen_ejecutivo`, then
  `MigrationReport.build(...)` computes the metrics in Python (`statistics.mean`) from the
  structured findings. The text layout is `MigrationReport.render()` — one method.
- **`ReporterAgent`** — `summarize(reports: list[MigrationReport]) -> str`: builds its
  prompt from `r.render()` of each mini-report and returns `model.invoke(...).text`.
  Skipped entirely with `--skip-reporter`.

All four agents take the bare model from `build_model` (`init_chat_model`); retry is the
model's own `max_retries` (cloud providers only — `ChatOllama` has none) plus the graph
`RetryPolicy`, nothing is wrapped. `ReviewerAgent` / `CoherenceAgent` also get
`SKILLS_BASE_PATH`; `agents/base.build_skill_agent`'s `create_agent` has **no middleware**
(the `load_skill` loop is bounded by langgraph's `recursion_limit`).
`load_prompt` (the only other helper in `agents/base.py`) loads a stripped plain-text
prompt from `src/prompts/`. `MiniReporter` / `Reporter` read the reply with
`response.text` (langchain-core native).

### Skills system (`src/skills.py`)

`load_skills` reads `src/skills/*/SKILL.md` — frontmatter parsed with the
`python-frontmatter` library (no regex), `name` / `description` into frozen `Skill`
dataclasses. Both agents load the whole `src/skills/` folder — descriptions go into the
system prompt (`skills_header`), full bodies are pulled in on demand via the single
`load_skill(skill_name)` tool (`make_load_skill_tool`; an unknown name raises
`ValueError`, which `create_agent`'s default tool-error handling feeds back to the model).
`skill_calls(messages)` extracts which skills a run actually loaded. The model picks the
relevant ones (`sql-code-review` / `sql-optimization` for the reviewer,
`rollback-coherence` for coherence). To add guidance for either agent, add a new
`SKILL.md` folder here.

### Review output is a Pydantic schema (`src/models.py`)

No text parsing, **and no tolerant normalization** — the schemas are strict; a mismatch
is a pydantic `ValidationError` that propagates out of the node and aborts the run (no
`_REVIEW_FALLO`, no fail-safe not-approved). `ReviewOutput` is the
`with_structured_output` schema for the reviewer; `from_output` runs `model_validate`
first so it takes the model instance *or* the dict some providers return.
`ReviewResult = ReviewOutput + skills_utilizadas`
(added by the worker, not the LLM); build it with `ReviewResult.from_output(output,
skills)` (no filtering — an empty finding can't exist, the fields are required).
`Finding.prioridad` is the `Prioridad` `StrEnum` (`CRÍTICO ALTO MEDIO BAJO MEJORA
OBSERVACION`); `titulo` / `riesgo` / `recomendacion` are required (`min_length=1`);
scores are `int` with `ge=0, le=10`. No aliases, no clamping — `"ALTA"`, `11`, `""` all
raise. `Finding.linea: int | None` feeds the SARIF region. `ReviewResult.render()` /
`Finding.render()` produce the text for logs and the MiniReporter's LLM context.

`MigrationReport` (same module, a `@dataclass`, **not** an LLM schema) is what
`MiniReporterAgent.generate` returns: `migration_id`, `scripts_revisados`,
`prom_seguridad/rendimiento/mantenibilidad: float | None`, `rollback_coherente: bool`,
`hallazgos_altos: list[str]`, `resumen_ejecutivo: str`. `MigrationReport.build(...)`
computes the metrics from structured `ScriptReview`s; `MigrationReport.render()` is the
one place the report's text layout lives.

`CoherenceOutput` (same module) is the `with_structured_output` schema for
`CoherenceAgent`: `resumen_forward` / `resumen_rollback` / `analisis_coherencia` prose
(optional, `default=""`) + `veredicto` (the `Veredicto` `StrEnum` `COHERENTE` /
`INCOMPLETO`, default `INCOMPLETO`, `.approved` helper) + `operaciones_sin_revertir`.
`.render()` produces the report text.

`reviewer_system.md` describes these fields to the model and carries a long numbered
"PROHIBIDO REPORTAR" list of known false positives — extend that list rather than
post-filtering findings in Python. Only the field names / enum values matter.

### SARIF (`src/sarif.py`)

`--sarif PATH` → `to_sarif(all_reviews, incoherent_migrations, scripts_root)` builds a
SARIF 2.1.0 doc. The prioridad → level map lives on `Prioridad.sarif_level`
(CRÍTICO/ALTO=`error`, MEDIO/BAJO=`warning`, MEJORA/OBSERVACION=`note`). Each finding is
a `result` located at the script's path
relative to `--scripts-path`, `region.startLine` = `finding.linea or 1`. Each incoherent
migration adds a `rollback/incompleto` `error` result. It's the only machine-readable
output — no custom JSON.

### Exit code (`decide_exit` in `src/main.py`)

`--fail-on` (CSV of prioridades, default `CRÍTICO`) → any finding with a matching
prioridad, **or** any incomplete rollback, → exit 1. `decide_exit` is a pure function
(unit-tested); it is the *only* thing that decides the exit code.

### Providers (`src/llm.py`)

`build_model(provider, base_url, model, api_key, *, temperature=0.0, timeout=120.0,
retries=2)` is a thin wrapper over **`init_chat_model`** (the recommended v1 way).
`ollama` → `model_provider="ollama"` (`num_ctx=32768`, `client_kwargs={"timeout": …}`);
`openai` / `openrouter` / `groq` → `model_provider="openai"` with `base_url` from
`PROVIDER_DEFAULT_URLS` and a throwaway `api_key` if none given. `retries` →
`max_retries` (the model's own backoff; `ChatOllama` ignores it — local endpoint, no
retry needed). Nothing is wrapped after construction — no `resilient`, no retry
middleware.
