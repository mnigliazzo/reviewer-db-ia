# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CI tool that reviews SQL Server (T-SQL) database migration scripts with a multi-agent
LangGraph pipeline before they are merged. It exits non-zero when it finds findings at
or above the `--fail-on` severity (default `CRÍTICO`) or an incomplete rollback, so it
can gate a merge. All prompts, reports, log messages, and most code comments are in
Spanish — keep new user-facing strings in Spanish.

## Running it

`run.ps1` (Windows) and `run.sh` (Linux/macOS/WSL/git-bash) are the direct-run
entrypoints. Both read a whitelisted subset of keys (`PROVIDER`, `MODEL_BASE_URL`,
`MODEL_AGENTS`, `SCRIPTS_PATH`, `LOG_LEVEL`, `REVIEWER_MAX_*`, `REVIEWER_FAIL_ON`,
`REVIEWER_LLM_TIMEOUT`, `REVIEWER_LLM_RETRIES`, `REVIEWER_SARIF`, `API_KEY`,
`SKIP_REPORTER`) from `.env` / `.env.local`; anything already in the
environment wins. They auto-select `.venv`. `.env.example` values must not carry
inline `# comments` — the parsers don't strip them.

```bash
cp .env.example .env      # then fill in values
./run.sh                  # Linux/macOS/WSL
.\run.ps1                 # Windows PowerShell
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
machine-readable output). `run.sh` / `run.ps1` expose these as `REVIEWER_FAIL_ON`,
`REVIEWER_LLM_TIMEOUT`, `REVIEWER_LLM_RETRIES`, `REVIEWER_SARIF`.

```bash
# Full pipeline
make install   # uv pip install -e .
make build     # only needed for MODE=docker
make run       # prepare-delta -> run-$(MODE) -> clean-tmp
make clean
```

`make run` dispatches on `MODE` (command-line var > `MODE=` in `.env` > `docker`;
invalid value → `$(error)`):
- `MODE=docker` → `docker compose run --rm reviewer`. The container's `CMD`
  (Dockerfile) is `bash run.sh`; `docker-compose.yml` has **no `command:`**, it only
  passes the `REVIEWER_*` / `PROVIDER` / … env vars through to the container (and sets
  `SCRIPTS_PATH=/app/scripts_review` via Dockerfile `ENV`).
- `MODE=local` → `bash run.sh` — the CLI runs in the repo `.venv`, no container.

Either way `run.sh` is the single source of truth for the env-var → CLI-flag mapping
(`run.ps1` mirrors it for Windows). `run-docker` / `run-local` are also callable
directly (without the prepare-delta / clean-tmp wrapper).

`make.ps1` is the Windows port of the `Makefile` (same targets, no `make`/bash needed);
it mirrors the Makefile the way `run.ps1` mirrors `run.sh`. Keep the two in sync when
changing orchestration (targets, `MODE` dispatch, the prepare-delta trim rules).
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
  `run.ps1` / `run.sh` (whitelisted keys), the Makefile (`ENV_FILE_NAME := .env`), and
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

### One LangGraph graph, driven by a plain loop (`src/graph.py` + `src/main.py`)

**Migration sweep** — `main.review_migrations` iterates the migrations **in order**
(plain `for`, no graph), calling `migration_graph.invoke(new_migration_state(...))` once
per migration. Forward scripts already reviewed accumulate in `previous_scripts` and are
fed to later migrations as `schema_context` (`build_schema_context`, capped by
`--max-schema-scripts`). After the loop it runs `ReporterAgent` once (unless
`--skip-reporter`). It returns `(all_reviews, incoherent_migrations)` for `decide_exit` /
SARIF.

**Migration graph** (`MigrationState`, the only compiled graph) — per migration:
`fan_out` → parallel `review_script` workers (one `Send` per forward script) → `gather`
fan-in → route to `escalate` if any worker set `has_critical`, else `coherence` →
`mini_reporter`. Parallel-worker state is merged with `operator.add` / `operator.or_`
reducers. `review_script` calls `reviewer.review(...)` and `coherence_node` calls
`coherence_agent.analyze(...)`; each is a single LangChain **`create_agent`** run that
loads skills via the `load_skill` tool and then returns the structured schema
(`ReviewOutput` / `CoherenceOutput`) as `result["structured_response"]`. No hand-rolled
tool loop, no text parsing.

There is no per-node safety net around the review or coherence work: a crashing review
or coherence check (LLM error, schema-`ValidationError`) propagates out of the node and
aborts the whole run with a non-zero exit — no synthetic `_REVIEW_FALLO` finding, no
fail-safe not-approved. A genuine `INCOMPLETO` veredicto still flows through normally
(`coherence_approved=False` → exit 1 with a clean message); only *exceptions* now crash.
The two exceptions: `mini_reporter_node` and the `ReporterAgent` call in
`review_migrations` swallow errors into a placeholder — the reports are informational and
never gate the merge.

### Agents (`src/agents/`)

- **`ReviewerAgent`** — reviews one script. `review(script, sql, schema_context)` runs a
  `create_agent` (tool: `load_skill`, `response_format=ReviewOutput`) and returns a
  `ReviewResult` (`ReviewOutput` + `skill_calls(messages)`). System prompt =
  `reviewer_system.md` + a generated skills header.
- **`CoherenceAgent`** — runs once per migration; checks the rollback reverts the
  forward. `analyze(migration, forward, rollback)` — same `create_agent` shape with
  `response_format=CoherenceOutput`. The
  rollback-completeness criteria live in the `rollback-coherence` skill, not the prompt.
  `CoherenceOutput.veredicto` is the strict `Veredicto` `StrEnum` (no Python
  normalization; an off-enum value is a `ValidationError` that propagates out of
  `coherence_node` and aborts the run); `.approved` is `veredicto is Veredicto.COHERENTE`. `CoherenceOutput.render()`
  produces the report (logged + fed to the MiniReporter) from the structured fields.
  `coherence_node` short-circuits to approved when a migration has no forward scripts.
- **`MiniReporterAgent`** — per-migration report: metrics computed in Python from
  structured findings + an LLM narrative summary, assembled into a fixed text layout.
- **`ReporterAgent`** — final executive report consolidating the mini-reports;
  skipped entirely with `--skip-reporter`.

`MiniReporterAgent` / `ReporterAgent` receive the model already wrapped by
`llm.resilient()` from `main.py` and consume a free-form reply with `response.text`
(langchain-core native). `ReviewerAgent` / `CoherenceAgent` get the bare model plus
`SKILLS_BASE_PATH` and `retries`; `agents/base.build_skill_agent` wires that into
`create_agent` (`ModelRetryMiddleware` when `retries > 0`, nothing otherwise — the
`load_skill` loop is bounded by langgraph's `recursion_limit`). `load_prompt` (the only
other helper in `agents/base.py`) loads a plain-text prompt from `src/prompts/`.

### Skills system (`src/skills.py`)

`load_skills` reads `src/skills/*/SKILL.md` (YAML frontmatter parsed with `yaml.safe_load`,
`name` / `description`) into frozen `Skill` dataclasses. Both agents load the whole
`src/skills/` folder — descriptions go into the system prompt, full bodies are pulled in
on demand via the `load_skill` tool (`make_load_skill_tool`; an unknown name raises
`ValueError`, which `create_agent`'s default `ToolErrorMiddleware` feeds back to the
model). `skill_calls(messages)` extracts which skills a run actually loaded. The model
picks the relevant ones (`sql-code-review` / `sql-optimization` for the reviewer,
`rollback-coherence` for coherence). To add guidance for either agent, add a new
`SKILL.md` folder here.

### Review output is a Pydantic schema (`src/models.py`)

No text parsing, **and no tolerant normalization** — the schemas are strict; a mismatch
is a pydantic `ValidationError` that propagates out of the node and aborts the run (no
`_REVIEW_FALLO`, no fail-safe not-approved). `ReviewOutput` is the `create_agent`
`response_format`. `ReviewResult = ReviewOutput + skills_utilizadas`
(added by the worker, not the LLM); build it with `ReviewResult.from_output(output,
skills)` (no filtering — an empty finding can't exist, the fields are required).
`Finding.prioridad` is the `Prioridad` `StrEnum` (`CRÍTICO ALTO MEDIO BAJO MEJORA
OBSERVACION`); `titulo` / `riesgo` / `recomendacion` are required (`min_length=1`);
scores are `int` with `ge=0, le=10`. No aliases, no clamping — `"ALTA"`, `11`, `""` all
raise. `Finding.linea: int | None` feeds the SARIF region. `ReviewResult.render()` /
`Finding.render()` produce the text for logs and the MiniReporter's LLM context.

`CoherenceOutput` (same module) is the `create_agent` `response_format` for
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
(unit-tested). `MigrationState.has_critical` only routes `escalate` inside the migration
graph (an early-exit optimization); it does not decide the exit code and is not read
outside the graph.

### Providers (`src/llm.py`)

`build_model(provider, base_url, model, api_key, *, temperature=0.0, timeout=120.0)` —
`ollama` (default, `ChatOllama`, `num_ctx=16384`, `client_kwargs={"timeout": …}`) or any
OpenAI-compatible endpoint (`openai` / `openrouter` / `groq` via `ChatOpenAI`,
`max_retries=0`, default URLs in `PROVIDER_DEFAULT_URLS`). `resilient(runnable, retries)`
wraps a runnable with `with_retry(stop_after_attempt=retries+1,
wait_exponential_jitter=True)`; it's used for the two reporter agents' plain `.invoke()`
calls. `ReviewerAgent` / `CoherenceAgent` don't use it — their retry is
`ModelRetryMiddleware` inside `create_agent`.
