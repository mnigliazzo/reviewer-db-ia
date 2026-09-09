# Ejecuta el reviewer directamente (Windows / PowerShell).
# Toma la config de .env (y .env.local si existe); una variable ya presente en el
# entorno tiene prioridad. Uso:  .\run.ps1
# NOTA: no escribe nada en $env: -- run.ps1 corre in-process al llamarse desde
# make.ps1, y ensuciar la sesion haria que un .env editado no se tome en el
# siguiente run de la misma terminal.
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Solo estas claves se leen del .env (evita arrastrar proxy/credenciales de Docker).
$AllowKeys = @(
    'PROVIDER', 'MODEL_BASE_URL', 'BASE_URL', 'MODEL_AGENT',
    'API_KEY', 'LOG_LEVEL', 'SCRIPTS_PATH', 'REVIEW_SCRIPTS_PATH', 'SKIP_REPORTER',
    'REVIEWER_MAX_SCHEMA_SCRIPTS',
    'REVIEWER_FAIL_ON', 'REVIEWER_LLM_TIMEOUT', 'REVIEWER_LLM_RETRIES', 'REVIEWER_SARIF'
)

function Import-DotEnv([string]$Path, [hashtable]$Into) {
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
        if ($Into.ContainsKey($key)) { continue }   # .env gana sobre .env.local
        $Into[$key] = $line.Substring($idx + 1).Trim().Trim('"').Trim("'").Trim()
    }
}

$DotEnv = @{}
Import-DotEnv (Join-Path $ScriptDir '.env') $DotEnv
Import-DotEnv (Join-Path $ScriptDir '.env.local') $DotEnv

# Valor de una clave: entorno real (no vacio) > .env > fallback.
function Cfg([string]$key, [string]$fallback = '') {
    $fromEnv = [Environment]::GetEnvironmentVariable($key)
    if (-not [string]::IsNullOrWhiteSpace($fromEnv)) { return $fromEnv.Trim() }
    if ($DotEnv.ContainsKey($key) -and $DotEnv[$key]) { return $DotEnv[$key].Trim() }
    return $fallback
}

# Fail-fast: sin .env ni variables en el entorno no hay nada que hacer.
$HasEnvFile = (Test-Path (Join-Path $ScriptDir '.env')) -or (Test-Path (Join-Path $ScriptDir '.env.local'))
if (-not $HasEnvFile -and -not (Cfg 'MODEL_BASE_URL') -and -not (Cfg 'BASE_URL')) {
    Write-Error "Falta .env (y no hay variables en el entorno). Copia el template:  cp .env.example .env"
    exit 1
}

$Provider         = Cfg 'PROVIDER'        'ollama'
$BaseUrl          = Cfg 'MODEL_BASE_URL'  (Cfg 'BASE_URL' 'http://localhost:11434')
$Model            = Cfg 'MODEL_AGENT'     'qwen2.5-coder'
$LogLevel         = Cfg 'LOG_LEVEL'       'INFO'
$ScriptsPath      = Cfg 'SCRIPTS_PATH'    (Cfg 'REVIEW_SCRIPTS_PATH' (Join-Path $ScriptDir 'tmp/db-script'))
$MaxSchemaScripts = Cfg 'REVIEWER_MAX_SCHEMA_SCRIPTS' '0'
$LlmTimeout       = Cfg 'REVIEWER_LLM_TIMEOUT'        '120'
$LlmRetries       = Cfg 'REVIEWER_LLM_RETRIES'        '2'
$FailOn           = Cfg 'REVIEWER_FAIL_ON'
$ApiKey           = Cfg 'API_KEY'
$Sarif            = Cfg 'REVIEWER_SARIF'
$SkipReporter     = Cfg 'SKIP_REPORTER'

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
if ($FailOn) { $cliArgs += @('--fail-on', $FailOn) }
if ($ApiKey) { $cliArgs += @('--api-key', $ApiKey) }
if ($Sarif)  { $cliArgs += @('--sarif', $Sarif) }
if ($SkipReporter -in @('1', 'true', 'True', 'yes', 'YES')) { $cliArgs += '--skip-reporter' }

& $Python @cliArgs
exit $LASTEXITCODE
