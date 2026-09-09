# Ejecuta el reviewer directamente (Windows / PowerShell).
# Toma la config de .env (y .env.local si existe); las variables ya presentes
# en el entorno tienen prioridad. Uso:  .\run.ps1
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Solo estas claves se leen del .env (evita arrastrar proxy/credenciales de Docker).
$AllowKeys = @(
    'PROVIDER', 'MODEL_BASE_URL', 'BASE_URL', 'MODEL_AGENT', 'MODEL_AGENTS',
    'API_KEY', 'LOG_LEVEL', 'SCRIPTS_PATH', 'REVIEW_SCRIPTS_PATH', 'SKIP_REPORTER',
    'REVIEWER_MAX_SCHEMA_SCRIPTS',
    'REVIEWER_FAIL_ON', 'REVIEWER_LLM_TIMEOUT', 'REVIEWER_LLM_RETRIES', 'REVIEWER_SARIF'
)

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    # -Encoding UTF8: el .env es UTF-8; sin esto Windows PowerShell 5.1 lo lee como
    # ANSI y rompe valores con acentos (ej: REVIEWER_FAIL_ON=CRITICO).
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim()
        if ($AllowKeys -notcontains $key) { continue }
        if (Test-Path "env:$key") { continue }   # el entorno gana
        $val = $line.Substring($idx + 1).Trim().Trim('"').Trim("'").Trim()
        Set-Item -Path "env:$key" -Value $val
    }
}

Import-DotEnv (Join-Path $ScriptDir '.env')
Import-DotEnv (Join-Path $ScriptDir '.env.local')

# Fail-fast: sin .env ni variables en el entorno no hay nada que hacer.
$HasEnvFile = (Test-Path (Join-Path $ScriptDir '.env')) -or (Test-Path (Join-Path $ScriptDir '.env.local'))
if (-not $HasEnvFile -and
    [string]::IsNullOrWhiteSpace($env:MODEL_BASE_URL) -and [string]::IsNullOrWhiteSpace($env:BASE_URL)) {
    Write-Error "Falta .env (y no hay variables en el entorno). Copia el template:  cp .env.example .env"
    exit 1
}

function Def($value, $fallback) { if ([string]::IsNullOrWhiteSpace($value)) { $fallback } else { $value.Trim() } }

$Provider         = Def $env:PROVIDER        'ollama'
$BaseUrl          = Def $env:MODEL_BASE_URL  (Def $env:BASE_URL 'http://localhost:11434')
$Model            = Def $env:MODEL_AGENTS    (Def $env:MODEL_AGENT 'qwen2.5-coder')
$LogLevel         = Def $env:LOG_LEVEL       'INFO'
$ScriptsPath      = Def $env:SCRIPTS_PATH    (Def $env:REVIEW_SCRIPTS_PATH (Join-Path $ScriptDir 'tmp/db-script'))
$MaxSchemaScripts = Def $env:REVIEWER_MAX_SCHEMA_SCRIPTS '0'
$LlmTimeout       = Def $env:REVIEWER_LLM_TIMEOUT        '120'
$LlmRetries       = Def $env:REVIEWER_LLM_RETRIES        '2'

# Python del venv del repo si no hay uno activo.
$Python = 'python'
if (-not $env:VIRTUAL_ENV -and (Test-Path (Join-Path $ScriptDir '.venv/Scripts/python.exe'))) {
    $Python = Join-Path $ScriptDir '.venv/Scripts/python.exe'
}

$cliArgs = @(
    '-m', 'src.main',
    '--log-level',          $LogLevel,
    '--scripts-path',       $ScriptsPath,
    '--provider',           $Provider,
    '--base-url',           $BaseUrl,
    '--model-agent',        $Model,
    '--max-schema-scripts', $MaxSchemaScripts,
    '--llm-timeout',        $LlmTimeout,
    '--llm-retries',        $LlmRetries
)
# --fail-on solo si esta seteado; el default (CRITICO) vive en src/main.py y asi
# run.ps1 no necesita un literal no-ASCII (Windows PowerShell 5.1 lo corrompe).
if (-not [string]::IsNullOrWhiteSpace($env:REVIEWER_FAIL_ON)) { $cliArgs += @('--fail-on', $env:REVIEWER_FAIL_ON) }
if (-not [string]::IsNullOrWhiteSpace($env:API_KEY)) { $cliArgs += @('--api-key', $env:API_KEY) }
if (-not [string]::IsNullOrWhiteSpace($env:REVIEWER_SARIF)) { $cliArgs += @('--sarif', $env:REVIEWER_SARIF) }
if ($env:SKIP_REPORTER -in @('1', 'true', 'True', 'yes', 'YES')) { $cliArgs += '--skip-reporter' }

& $Python @cliArgs
exit $LASTEXITCODE
