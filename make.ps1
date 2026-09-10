<#
  Equivalente del Makefile para Windows (no requiere make ni bash).
  Espeja los targets del Makefile. El entrypoint del CLI es run.py (comun a ambos).
  Solo ASCII: Windows PowerShell 5.1 sin BOM interpreta el script como ANSI.

  Uso:
    .\make.ps1 <target> [-Mode docker|local]

  Targets: install | build | run | run-docker | run-local | prepare-delta
           | down | clean | clean-tmp | check-env | help
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'install', 'build', 'run', 'run-docker', 'run-local',
                 'prepare-delta', 'down', 'clean', 'clean-tmp', 'check-env')]
    [string]$Target = 'help',

    [ValidateSet('docker', 'local')]
    [string]$Mode,

    [ValidateSet('clone', 'folder')]
    [string]$Source
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$EnvFileName = '.env'
$EnvFile     = Join-Path $PSScriptRoot $EnvFileName
$ComposeEnv  = @('--env-file', $EnvFileName)
$FolderTmp   = Join-Path $PSScriptRoot 'tmp/db-script'
$FileVersion = 'current_db_version.txt'

# ---- helpers ---------------------------------------------------------------

function Get-EnvValue([string]$pattern) {
    # Espeja  grep <pattern> .env | cut -d'=' -f2 | tr -d '\r\n'
    # Ignora comentarios y lineas sin '=' (si no, [1] es null y .Trim() revienta).
    if (-not (Test-Path $EnvFile)) { return '' }
    # -Encoding UTF8: Windows PowerShell 5.1 lee UTF-8 como ANSI sin esto.
    $line = Get-Content -LiteralPath $EnvFile -Encoding UTF8 |
        Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' -and $_ -match $pattern } |
        Select-Object -First 1
    if (-not $line) { return '' }
    $val = ($line -split '=', 2)[1]
    if ($null -eq $val) { return '' }
    return $val.Trim() -replace '[\r\n]', ''
}

function Resolve-Mode {
    if ($Mode) { return $Mode }
    $fromEnv = (Get-EnvValue '^MODE=') -replace '\s*#.*$', ''
    if ($fromEnv) {
        if ($fromEnv -notin @('docker', 'local')) {
            throw "MODE invalido: '$fromEnv'. Valores validos: docker | local"
        }
        return $fromEnv
    }
    return 'docker'
}

function Resolve-Source {
    if ($Source) { return $Source }
    $fromEnv = (Get-EnvValue '^SOURCE=') -replace '\s*#.*$', ''
    if ($fromEnv) {
        if ($fromEnv -notin @('clone', 'folder')) {
            throw "SOURCE invalido: '$fromEnv'. Valores validos: clone | folder"
        }
        return $fromEnv
    }
    return 'clone'
}

function Invoke-Native([Parameter(Mandatory)][scriptblock]$Cmd) {
    & $Cmd
    if ($LASTEXITCODE -ne 0) { throw "Comando fallo (exit $LASTEXITCODE): $Cmd" }
}

function Remove-Tree([string]$path) {
    # rmdir de cmd aguanta paths largos (MAX_PATH) mejor que Remove-Item en PS 5.1.
    if (-not (Test-Path -LiteralPath $path)) { return }
    & cmd /c rmdir /s /q "$path" 2>&1 | Out-Null
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

# ---- targets -------------------------------------------------------------

function Target-Help {
    Write-Host ''
    Write-Host '  .\make.ps1 install           - Instala deps con uv'
    Write-Host '  .\make.ps1 build             - Construye las imagenes Docker'
    Write-Host "  .\make.ps1 run                 - Auditoria IA (MODE=$(Resolve-Mode)  SOURCE=$(Resolve-Source))"
    Write-Host '  .\make.ps1 run -Mode local     - Igual, pero corriendo el CLI en el venv local (via run.py)'
    Write-Host '  .\make.ps1 run -Mode docker    - Igual, pero dentro del contenedor'
    Write-Host '  .\make.ps1 run -Source folder  - Usa la carpeta del .env directamente, sin clonar db-scripts'
    Write-Host '  .\make.ps1 clean               - Limpia contenedores y residuos temporales'
    Write-Host ''
}

function Target-Install {
    Invoke-Native { uv pip install -e . }
}

function Target-CheckEnv {
    if (-not (Test-Path $EnvFile)) {
        throw "Falta $EnvFileName. Copia el template:  Copy-Item .env.example .env"
    }
}

function Target-Build {
    Target-CheckEnv
    Invoke-Native { docker compose @ComposeEnv build reviewer }
}

function Target-PrepareDelta {
    Target-CheckEnv
    Write-Host '>> Iniciando preparacion del entorno delta...'
    Remove-Tree $FolderTmp

    $env:GIT_USERNAME = Get-EnvValue 'GIT_USER'
    $b64 = Get-EnvValue 'GIT_PASSWORD'
    if ($b64) {
        $env:GIT_PASSWORD = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
    }
    $branch = Get-EnvValue 'GIT_BRANCH'
    $url    = Get-EnvValue 'REPO_URL'

    Write-Host ">> Clonando rama $branch..."
    # core.longpaths: el repo tiene archivos que exceden MAX_PATH (260) en Windows.
    Invoke-Native { git -c core.longpaths=true clone --depth 1 -b $branch --single-branch $url $FolderTmp }

    $versionFile = Join-Path $FolderTmp $FileVersion
    $current = (Get-Content -Raw -LiteralPath $versionFile).Trim()
    $parts   = $current -split '/'
    $curYear = $parts[0].Trim()
    $curTs   = if ($parts.Count -gt 1) { $parts[1].Trim() } else { '' }

    if (-not $curYear -or -not $curTs) {
        throw "No se pudo determinar la version actual de la DB ($versionFile)."
    }
    Write-Host ">> Version DB actual -> Anio: [$curYear] | Timestamp: [$curTs]"

    $curYearN = [int64]$curYear
    $curTsN   = [int64]$curTs

    foreach ($yearDir in Get-ChildItem -Directory -LiteralPath $FolderTmp) {
        if ($yearDir.Name -notmatch '^\d+$') {
            Write-Host "   borrando carpeta no-migracion: $($yearDir.Name)"
            Remove-Tree $yearDir.FullName
            continue
        }
        $yearN = [int64]$yearDir.Name
        if ($yearN -lt $curYearN) {
            Write-Host "   borrando anio antiguo: $($yearDir.Name)"
            Remove-Tree $yearDir.FullName
            continue
        }
        if ($yearN -ne $curYearN) { continue }

        foreach ($tsDir in Get-ChildItem -Directory -LiteralPath $yearDir.FullName) {
            if ($tsDir.Name -notmatch '^\d+$') { continue }
            if ([int64]$tsDir.Name -le $curTsN) {
                Write-Host "   borrando migracion antigua: $($yearDir.Name)/$($tsDir.Name)"
                Remove-Tree $tsDir.FullName
            }
            else {
                Write-Host "   conservando delta nuevo: $($yearDir.Name)/$($tsDir.Name)"
            }
        }
        if (-not (Get-ChildItem -Force -LiteralPath $yearDir.FullName)) {
            Remove-Tree $yearDir.FullName
        }
    }
    Write-Host ">> Filtro completado. Carpetas remanentes en $FolderTmp"
}

function Target-RunDocker {
    Write-Host '>> Lanzando agente de IA (docker) sobre el delta...'
    Invoke-Native { docker compose @ComposeEnv run --rm reviewer }
}

function Target-RunLocal {
    Write-Host '>> Lanzando agente de IA (local / venv) sobre el delta...'
    # run.py lee .env, re-ejecuta con el python del venv y arma los flags del CLI.
    & python (Join-Path $PSScriptRoot 'run.py')
    if ($LASTEXITCODE -ne 0) { throw "run.py salio con codigo $LASTEXITCODE" }
}

function Target-Run {
    $clone = (Resolve-Source) -eq 'clone'
    if ($clone) { Target-PrepareDelta }
    else { Write-Host '>> SOURCE=folder: uso la carpeta del .env, sin clonar db-scripts.' }
    $failed = $null
    try {
        if ((Resolve-Mode) -eq 'local') { Target-RunLocal } else { Target-RunDocker }
    }
    catch { $failed = $_ }
    finally { if ($clone) { Target-CleanTmp } }
    if ($failed) { throw $failed }
}

function Target-Down {
    Invoke-Native { docker compose @ComposeEnv down }
}

function Target-CleanTmp {
    Write-Host '>> Eliminando archivos temporales del repo clonado...'
    Remove-Tree $FolderTmp
}

function Target-Clean {
    Target-CleanTmp
    Invoke-Native { docker compose @ComposeEnv down -v --remove-orphans }
}

# ---- dispatch ------------------------------------------------------------

switch ($Target) {
    'help'          { Target-Help }
    'install'       { Target-Install }
    'check-env'     { Target-CheckEnv }
    'build'         { Target-Build }
    'prepare-delta' { Target-PrepareDelta }
    'run'           { Target-Run }
    'run-docker'    { Target-RunDocker }
    'run-local'     { Target-RunLocal }
    'down'          { Target-Down }
    'clean-tmp'     { Target-CleanTmp }
    'clean'         { Target-Clean }
}
