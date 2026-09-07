# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CI tool that reviews SQL Server (T-SQL) database migration scripts with a multi-agent
LangGraph pipeline before they are merged. It exits non-zero when it finds `CRÍTICO`
findings or an incomplete rollback, so it can gate a merge. All prompts, reports, log
messages, and most code comments are in Spanish — keep new user-facing strings in Spanish.

## Running it

```powershell
# Local dev (Windows, against a local Ollama). Edit vars at the top first.
.\run.ps1
```

```bash
# Direct invocation
python -m src.main --scripts-path <ROOT> --base-url <URL> --model-agent <MODEL> \
    [--provider ollama|openai|openrouter|groq] [--api-key KEY] [--skip-reporter] \
    [--max-tool-rounds N] [--max-schema-scripts N] [--log-level INFO]
```

`--scripts-path`, `--base-url`, `--model-agent` are required. `--max-tool-rounds 0` and
`--max-schema-scripts 0` mean *unlimited* (not "disabled").

```bash
# Docker / full pipeline (Linux, needs .env.jali — not committed)
make build
make run     # runs `prepare-delta` then `docker compose run reviewer`, then cleans tmp
make clean
```

`make prepare-delta` shallow-clones the external `db-scripts` GitLab repo into
`./tmp/db-script`, reads `current_db_version.txt` (format `YEAR/TIMESTAMP`), and deletes
every migration folder at or below that version, leaving only the new delta for review.

There is **no test suite and no linter configured**. Python >= 3.12; deps
(`langchain`, `langgraph`, `langchain-ollama`, `langchain-openai`) install via
`uv pip install -e .`.

## Config notes

- `.env` is committed and holds a base64-encoded `GIT_PASSWORD`. The Makefile instead
  reads `.env.jali`, which is gitignored (`.env*`). `docker-compose.yml` is driven
  entirely by env vars (Docker registry, proxy, model, paths).
- GitLab CI (`-.gitlab-ci.yml` — the leading `-` in the name is intentional/odd) only
  builds and pushes the Docker image, and only on `master`.
- `.claude/skills/` is unrelated to `src/skills/` (see below).

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
reducers. Each `review_script` worker runs its **own tool-call loop**: it repeatedly
invokes `model_with_tools`, executes any `load_skill` tool calls, and stops when the
model returns no more tool calls or `--max-tool-rounds` is hit.

### Agents (`src/agents/`)

- **`ReviewerAgent`** — reviews one script. Binds the `load_skill` tool, builds
  system prompt = `reviewer_system.md` + a generated skills header.
- **`CoherenceAgent`** — runs once per migration; checks the rollback reverts the
  forward. Approval is decided by a literal substring match on
  `"RESULTADO: COHERENTE"` in the model output — the `coherence_system.md` prompt is
  contracted to end with that exact line or `RESULTADO: INCOMPLETO`.
- **`MiniReporterAgent`** — per-migration report: metrics computed in Python from
  structured findings + an LLM narrative summary, assembled into a fixed text layout.
- **`ReporterAgent`** — final executive report consolidating the mini-reports;
  skipped entirely with `--skip-reporter`.

All agents share `_load_prompt` from `reviewer.py` and load a plain-text prompt from
`src/prompts/`.

### Skills system (`src/skill_middleware.py`)

`load_skills_from_disk` reads `src/skills/*/SKILL.md` (YAML frontmatter with
`name` / `description`). Only the descriptions go into the reviewer's system prompt;
full skill bodies are pulled in on demand when the model calls the `load_skill`
tool. To add review guidance, add a new `SKILL.md` folder here.

### Review output format is a contract (`src/models.py`)

The reviewer produces **plain text, no Markdown**, and `parse_review_text` regex-parses
it back into `ReviewResult` / `Finding`:

- `_SCORE_RE` matches `Seguridad|Rendimiento|Mantenibilidad: N/10`.
- `_HEADER_RE` matches `[PRIORIDAD] [CATEGORIA] [skill-name]: Titulo`, then
  `Ubicacion:` / `Riesgo:` / `Recomendacion:` lines.
- `PRIORIDAD` must be exactly one of `CRÍTICO ALTO MEDIO BAJO MEJORA OBSERVACION`.
- `has_critical` (any finding with `prioridad == "CRÍTICO"`) drives the pipeline exit
  code.

If you change `reviewer_system.md`'s output format, update these regexes in lockstep,
and vice versa. `reviewer_system.md` also carries a long numbered "PROHIBIDO REPORTAR"
list of known false positives that must stay suppressed — extend that list rather than
post-filtering findings in Python.

### Providers (`build_model` in `src/main.py`)

`ollama` (default, `ChatOllama`, `num_ctx=16384`) or any OpenAI-compatible endpoint
(`openai` / `openrouter` / `groq` via `ChatOpenAI`, with default base URLs in
`PROVIDER_DEFAULT_URLS`).
