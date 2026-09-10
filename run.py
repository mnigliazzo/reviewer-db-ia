#!/usr/bin/env python3
"""Entrypoint directo del reviewer (reemplaza a run.sh / run.ps1).

Lee ``.env`` / ``.env.local`` (subconjunto whitelisteado de claves), le da
precedencia al entorno real, arma los flags del CLI y llama a ``src.main``. No
escribe nada en el entorno. ``make`` / ``make.ps1`` siguen siendo la capa que
depende del entorno (prepare-delta, docker).

Uso:  python run.py   (o  ./run.py)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Solo estas claves se leen del .env (no arrastrar proxy/credenciales de Docker).
# REVIEW_SCRIPTS_PATH no está: eso lo usa solo docker-compose (source del volumen);
# el CLI consume SCRIPTS_PATH.
_ALLOWED = frozenset({
    "PROVIDER", "MODEL_BASE_URL", "MODEL_AGENT", "API_KEY", "LOG_LEVEL", "SCRIPTS_PATH",
    "SKIP_REPORTER", "REVIEWER_MAX_SCHEMA_SCRIPTS", "REVIEWER_FAIL_ON",
    "REVIEWER_LLM_TIMEOUT", "REVIEWER_LLM_RETRIES", "REVIEWER_NUM_CTX", "REVIEWER_SARIF",
})


def _reexec_in_venv() -> None:
    """Si hay un ``.venv`` en el repo y no lo estamos usando, re-ejecuta con su python."""
    sub = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    venv = ROOT / ".venv" / sub
    if os.environ.get("VIRTUAL_ENV") or not venv.exists():
        return
    if Path(sys.executable).resolve() == venv.resolve():
        return
    sys.exit(subprocess.run([str(venv), str(Path(__file__).resolve()), *sys.argv[1:]]).returncode)


def _read_env_file(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not path.is_file():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in _ALLOWED:
            cfg[key] = value.strip().strip('"').strip("'")
    return cfg


def _load_config() -> tuple[dict[str, str], bool]:
    files = (ROOT / ".env", ROOT / ".env.local")   # .env.local pisa a .env
    cfg: dict[str, str] = {}
    for f in files:
        cfg.update(_read_env_file(f))
    return cfg, any(f.is_file() for f in files)


def _build_argv(cfg: dict[str, str]) -> list[str]:
    # entorno real (no vacío) > .env > default
    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or cfg.get(key) or default

    argv = [
        "--provider", get("PROVIDER", "ollama"),
        "--base-url", get("MODEL_BASE_URL", "http://localhost:11434"),
        "--model-agent", get("MODEL_AGENT", "qwen2.5-coder").strip(),
        "--scripts-path", get("SCRIPTS_PATH", str(ROOT / "tmp" / "db-script")),
        "--log-level", get("LOG_LEVEL", "INFO"),
        "--max-schema-scripts", get("REVIEWER_MAX_SCHEMA_SCRIPTS", "0"),
        "--llm-timeout", get("REVIEWER_LLM_TIMEOUT", "120"),
        "--llm-retries", get("REVIEWER_LLM_RETRIES", "2"),
        "--num-ctx", get("REVIEWER_NUM_CTX", "32768"),
    ]
    if get("REVIEWER_FAIL_ON"):
        argv += ["--fail-on", get("REVIEWER_FAIL_ON")]
    if get("API_KEY"):
        argv += ["--api-key", get("API_KEY")]
    if get("REVIEWER_SARIF"):
        argv += ["--sarif", get("REVIEWER_SARIF")]
    if get("SKIP_REPORTER").lower() in ("1", "true", "yes"):
        argv += ["--skip-reporter"]
    return argv


def main() -> int:
    _reexec_in_venv()
    os.chdir(ROOT)

    cfg, has_env_file = _load_config()
    if not has_env_file and not os.environ.get("MODEL_BASE_URL"):
        sys.stderr.write(
            "ERROR: falta .env (y no hay variables en el entorno). "
            "Copiá el template:  cp .env.example .env\n"
        )
        return 1

    from src.main import main as run_reviewer
    return run_reviewer(_build_argv(cfg))


if __name__ == "__main__":
    sys.exit(main())
