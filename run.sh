#!/usr/bin/env bash
# Ejecuta el reviewer directamente (Linux / macOS / WSL / git-bash).
# Toma la config de .env (y .env.local si existe); las variables ya presentes
# en el entorno tienen prioridad. Uso:  ./run.sh   (o  bash run.sh)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Solo estas claves se leen del .env (evita arrastrar proxy/credenciales de Docker).
_allowed_key() {
    case "$1" in
        PROVIDER|MODEL_BASE_URL|BASE_URL|MODEL_AGENT|MODEL_AGENTS|API_KEY|LOG_LEVEL| \
        SCRIPTS_PATH|REVIEW_SCRIPTS_PATH|SKIP_REPORTER| \
        REVIEWER_MAX_SCHEMA_SCRIPTS|REVIEWER_FAIL_ON|REVIEWER_LLM_TIMEOUT| \
        REVIEWER_LLM_RETRIES|REVIEWER_SARIF) return 0 ;;
        *) return 1 ;;
    esac
}

load_dotenv() {
    local file="$1" line key val
    [ -f "$file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"          # ltrim
        case "$line" in ''|\#*) continue ;; esac
        [ "${line#*=}" = "$line" ] && continue            # sin '='
        key="${line%%=*}"; key="$(printf '%s' "$key" | tr -d '[:space:]')"
        _allowed_key "$key" || continue
        [ -n "${!key:-}" ] && continue                    # el entorno gana
        val="${line#*=}"
        val="${val%"${val##*[![:space:]]}"}"              # rtrim
        val="${val#\"}"; val="${val%\"}"
        val="${val#\'}"; val="${val%\'}"
        export "$key=$val"
    done < "$file"
}

load_dotenv "$SCRIPT_DIR/.env"
load_dotenv "$SCRIPT_DIR/.env.local"

# Fail-fast: sin .env ni variables en el entorno no hay nada que hacer.
if [ ! -f "$SCRIPT_DIR/.env" ] && [ ! -f "$SCRIPT_DIR/.env.local" ] \
   && [ -z "${MODEL_BASE_URL:-${BASE_URL:-}}" ]; then
    printf 'ERROR: falta .env (y no hay variables en el entorno).\n' >&2
    printf '       Copiá el template:  cp .env.example .env\n' >&2
    exit 1
fi

PROVIDER="${PROVIDER:-ollama}"
BASE_URL="${MODEL_BASE_URL:-${BASE_URL:-http://localhost:11434}}"
MODEL="${MODEL_AGENTS:-${MODEL_AGENT:-qwen2.5-coder}}"
MODEL="$(printf '%s' "$MODEL" | xargs)"                   # trim
LOG_LEVEL="${LOG_LEVEL:-INFO}"
SCRIPTS_PATH="${SCRIPTS_PATH:-${REVIEW_SCRIPTS_PATH:-$SCRIPT_DIR/tmp/db-script}}"
MAX_SCHEMA_SCRIPTS="${REVIEWER_MAX_SCHEMA_SCRIPTS:-0}"
FAIL_ON="${REVIEWER_FAIL_ON:-CRÍTICO}"
LLM_TIMEOUT="${REVIEWER_LLM_TIMEOUT:-120}"
LLM_RETRIES="${REVIEWER_LLM_RETRIES:-2}"

# Python del venv del repo si no hay uno activo.
PYTHON="python"
if [ -z "${VIRTUAL_ENV:-}" ]; then
    if   [ -x "$SCRIPT_DIR/.venv/bin/python" ];        then PYTHON="$SCRIPT_DIR/.venv/bin/python"
    elif [ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]; then PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
    fi
fi

set -- -m src.main \
    --log-level          "$LOG_LEVEL" \
    --scripts-path       "$SCRIPTS_PATH" \
    --provider           "$PROVIDER" \
    --base-url           "$BASE_URL" \
    --model-agent        "$MODEL" \
    --max-schema-scripts "$MAX_SCHEMA_SCRIPTS" \
    --fail-on            "$FAIL_ON" \
    --llm-timeout        "$LLM_TIMEOUT" \
    --llm-retries        "$LLM_RETRIES"

[ -n "${API_KEY:-}" ] && set -- "$@" --api-key "$API_KEY"
[ -n "${REVIEWER_SARIF:-}" ] && set -- "$@" --sarif "$REVIEWER_SARIF"
case "${SKIP_REPORTER:-}" in 1|true|True|yes|YES) set -- "$@" --skip-reporter ;; esac

exec "$PYTHON" "$@"
