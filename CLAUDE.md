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
    [--max-tool-rounds N] [--max-schema-scripts N] [--log-level INFO] \
    [--temperature 0.0] [--llm-timeout 120] [--llm-retries 2] \
    [--fail-on CRÍTICO[,ALTO,...]] [--sarif PATH]
```

`--scripts-path`, `--base-url`, `--model-agent` are required. `--max-tool-rounds 0` and
`--max-schema-scripts 0` mean *unlimited* (not "disabled"). `--fail-on` (default
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

### Two nested LangGraph graphs (`src/graph.py`)

**Pipeline graph** (`PipelineState`) — processes migrations **sequentially**. The
`run_migration` node pops one migration off `migrations_queue`, runs the migration
graph on it, then conditionally loops back to itself until the queue is empty, then
goes to `global_reporter`. Forward scripts already reviewed accumulate in
`previous_scripts` and are fed to later migrations as `schema_context`
(`_build_schema_context`, capped by `--max-schema-scripts`).

**Migration graph** (`MigrationState`) — per migration:
`fan_out` → parallel `review_script` workers (one `Send` per forward script) → `gather`
fan-in → route to `escalate` if any worker set `has_critical`, else `coherence` →
`mini_reporter`. Parallel-worker state is merged with `operator.add` / boolean-OR
reducers. Each `review_script` worker is **two-phase** (in `graph.py`):
1. `_load_skills_loop` — repeatedly invokes `model_with_tools`, executes any
   `load_skill` tool calls, stops when the model asks for no more tools or
   `--max-tool-rounds` is hit. Returns the skill names loaded.
2. `reviewer.finalize(messages)` — one tool-less call via `with_structured_output`
   that returns a validated `ReviewOutput` (scores + `hallazgos`). No text parsing.

The whole worker body is wrapped in try/except — a crashing review (LLM error,
schema-validation failure) yields the synthetic `_REVIEW_FALLO` `OBSERVACION` finding
and the pipeline continues; it does **not** set `has_critical`, so it doesn't gate the
merge. `coherence_node` is fail-safe: on exception it returns
`coherence_approved=False` (an unverifiable rollback blocks). `mini_reporter_node` /
`global_reporter_node` swallow exceptions into a placeholder string (the reports are
informational).

### Agents (`src/agents/`)

- **`ReviewerAgent`** — reviews one script. Binds the `load_skill` tool for phase 1
  and exposes `finalize()` (phase 2) which calls `model.with_structured_output(
  ReviewOutput)`. System prompt = `reviewer_system.md` + a generated skills header.
  All runnables are wrapped with `llm.resilient()` (retry + backoff).
- **`CoherenceAgent`** — runs once per migration; checks the rollback reverts the
  forward. Approval is decided by `parse_coherence_verdict` (in `coherence.py`), a
  line-anchored regex: a line that is exactly `RESULTADO: COHERENTE` → approved, a line
  starting `RESULTADO: INCOMPLETO` → not approved, neither present → not approved + a
  `WARNING`. The `coherence_system.md` prompt is contracted to end with one of those
  two lines.
- **`MiniReporterAgent`** — per-migration report: metrics computed in Python from
  structured findings + an LLM narrative summary, assembled into a fixed text layout.
- **`ReporterAgent`** — final executive report consolidating the mini-reports;
  skipped entirely with `--skip-reporter`.

`CoherenceAgent` / `MiniReporterAgent` / `ReporterAgent` receive the model already
wrapped by `llm.resilient()` from `main.py`; `ReviewerAgent` gets the bare model plus a
`retries` int (it must `bind_tools` / `with_structured_output` first, then wrap).

All agents share `load_prompt` and `message_text` from `src/agents/base.py` and load a
plain-text prompt from `src/prompts/`. `message_text` normalizes an LLM response's
`content` (which some OpenAI-compatible providers return as a list of blocks) to `str`;
use it everywhere a free-form `.content` is consumed.

### Skills system (`src/skill_middleware.py`)

`load_skills_from_disk` reads `src/skills/*/SKILL.md` (YAML frontmatter with
`name` / `description`). Only the descriptions go into the reviewer's system prompt;
full skill bodies are pulled in on demand when the model calls the `load_skill`
tool. To add review guidance, add a new `SKILL.md` folder here.

### Review output is a Pydantic schema (`src/models.py`)

No text parsing. `Finding` and `ReviewOutput` (scores 0-10 + `hallazgos`) are the schema
handed to `model.with_structured_output()`. `ReviewResult = ReviewOutput +
skills_utilizadas` (added by the worker, not the LLM); build it with
`ReviewResult.from_output(output, skills)`. `Finding.prioridad` is a `Literal` of
`CRÍTICO ALTO MEDIO BAJO MEJORA OBSERVACION` — an out-of-set value is a pydantic
`ValidationError` (→ caught by the worker → `_REVIEW_FALLO`). `Finding.linea: int | None`
feeds the SARIF region. `format_review()` renders a `ReviewResult` to text for logs and
the MiniReporter's LLM context.

`reviewer_system.md` describes these fields to the model and carries a long numbered
"PROHIBIDO REPORTAR" list of known false positives — extend that list rather than
post-filtering findings in Python. There is no format contract to keep in lockstep any
more; only the field names / `Literal` values matter.

### SARIF (`src/sarif.py`)

`--sarif PATH` → `to_sarif(all_reviews, incoherent_migrations, scripts_root)` builds a
SARIF 2.1.0 doc. prioridad → level: CRÍTICO/ALTO=`error`, MEDIO/BAJO=`warning`,
MEJORA/OBSERVACION=`note`. Each finding is a `result` located at the script's path
relative to `--scripts-path`, `region.startLine` = `finding.linea or 1`. Each incoherent
migration adds a `rollback/incompleto` `error` result. It's the only machine-readable
output — no custom JSON.

### Exit code (`decide_exit` in `src/main.py`)

`--fail-on` (CSV of prioridades, default `CRÍTICO`) → any finding with a matching
prioridad, **or** any incomplete rollback, → exit 1. `decide_exit` is a pure function
(unit-tested). The graph's `has_critical` still only routes `escalate` (an early-exit
optimization); it does not decide the exit code.

### Providers (`src/llm.py`)

`build_model(provider, base_url, model, api_key, *, temperature=0.0, timeout=120.0)` —
`ollama` (default, `ChatOllama`, `num_ctx=16384`, `client_kwargs={"timeout": …}`) or any
OpenAI-compatible endpoint (`openai` / `openrouter` / `groq` via `ChatOpenAI`,
`max_retries=0`, default URLs in `PROVIDER_DEFAULT_URLS`). `resilient(runnable, retries)`
wraps the final runnable with `with_retry(stop_after_attempt=retries+1,
wait_exponential_jitter=True)` — applied after `bind_tools` / `with_structured_output`,
never before.
