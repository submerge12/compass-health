# start-health-system.ps1 - M15: one-command startup for the whole local stack.
#
# Order (each stage must be healthy before the next is announced):
#   1. PostgreSQL (docker compose, pgvector :5433)
#   2. Health Domain API (compress_health_agent serve:display, :8788, service-auth)
#   3. FastAPI BFF (compass-health backend, :8000, HEALTH_DOMAIN_* wired)
#   4. Static frontend (:5500)
#
# Rollback: the original start.bat still starts only FastAPI + static frontend.
# Set HEALTH_DOMAIN_MODE=off on the backend to disable the BFF without touching
# anything else.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start-health-system.ps1

$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path -Parent $PSScriptRoot        # compass-health/
$AgentDir   = Join-Path (Split-Path -Parent $RepoRoot) "compress_health_agent"
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"

$DomainToken  = if ($env:HEALTH_DOMAIN_TOKEN) { $env:HEALTH_DOMAIN_TOKEN } else { "dev-local-svc-token" }
$DomainUrl    = if ($env:HEALTH_DOMAIN_URL)   { $env:HEALTH_DOMAIN_URL }   else { "http://127.0.0.1:8788" }
$DatabaseUrl  = if ($env:DATABASE_URL)        { $env:DATABASE_URL }        else { "postgres://compass:compass@localhost:5433/compass_health" }

# HttpClient with the system proxy explicitly disabled: on machines with a
# local proxy (dev tunnels etc.), WinINET-backed Invoke-WebRequest would fail
# on http://localhost/* probes even when the service is up.
Add-Type -AssemblyName System.Net.Http
$Script:Http = New-Object System.Net.Http.HttpClient
$Script:Http.Timeout = New-Object System.TimeSpan(0, 0, 3)

function Wait-Http($Url, $Headers, $Stage, $Attempts = 30) {
    if ($Headers) {
        foreach ($key in $Headers.Keys) { $Script:Http.DefaultRequestHeaders.Add($key, $Headers[$key]) }
    }
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $resp = $Script:Http.GetAsync($Url).GetAwaiter().GetResult()
            if ($resp.IsSuccessStatusCode) {
                Write-Host "[OK] $Stage ready ($Url)" -ForegroundColor Green
                return $true
            }
        } catch { Start-Sleep -Seconds 2 }
    }
    Write-Host "[FAIL] $Stage did not become ready: $Url" -ForegroundColor Red
    return $false
}

Write-Host "=== Compass Health system startup (M15) ===" -ForegroundColor Cyan

# -- 1. PostgreSQL ----------------------------------------------------------
$pgRunning = docker ps --filter "name=compass-health-pg" --filter "status=running" --format "{{.Names}}"
if (-not $pgRunning) {
    $existing = docker ps -a --filter "name=compass-health-pg" --format "{{.Names}}"
    if ($existing) {
        Write-Host "[..] starting existing container compass-health-pg (data preserved)"
        docker start compass-health-pg | Out-Null
    } else {
        Push-Location $AgentDir
        docker compose up -d
        Pop-Location
    }
}
$pgReady = docker exec compass-health-pg pg_isready -U compass -d compass_health
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL not ready: $pgReady" }
Write-Host "[OK] PostgreSQL ready (:5433)" -ForegroundColor Green

# -- 1b. Schema migration gate (WO-HS-01 / M16) ------------------------------
# Migrations run before any service starts; a failed migration aborts the
# whole startup instead of booting APIs against an incompatible schema.
Push-Location $AgentDir
$env:DATABASE_URL = $DatabaseUrl
node --import tsx src/db/migrate.ts
$migrateExit = $LASTEXITCODE
Pop-Location
if ($migrateExit -ne 0) { throw "Schema migration gate failed - fix migrations before starting services." }
Write-Host "[OK] Schema migrations + compatibility gate passed" -ForegroundColor Green

# -- 2. Health Domain API ---------------------------------------------------
$domainUp = $false
try { $domainUp = (Invoke-WebRequest -Uri "$DomainUrl/api/health" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch {}
if (-not $domainUp) {
    $domainCmd = "cd '$AgentDir'; `$env:DATABASE_URL = '$DatabaseUrl'; `$env:COMPASS_DISPLAY_TOKEN = '$DomainToken'; pnpm serve:display"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $domainCmd
    if (-not (Wait-Http "$DomainUrl/api/health" @{ Authorization = "Bearer $DomainToken" } "Health Domain API (:8788)")) {
        throw "Health Domain API failed to start - check its window for errors."
    }
} else {
    Write-Host "[OK] Health Domain API already running (:8788)" -ForegroundColor Green
}

# -- 3. FastAPI BFF ---------------------------------------------------------
$bffUp = $false
try { $bffUp = (Invoke-WebRequest -Uri "http://localhost:8000/healthz" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch {}
if (-not $bffUp) {
    # auth.py refuses to boot without SECRET_KEY. If backend/.env defines one
    # (normal deployment), let it win; otherwise inject a dev-only key.
    $envFile = Join-Path $BackendDir ".env"
    $secretPrefix = ""
    $hasSecret = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "^\s*SECRET_KEY\s*=" -Quiet)
    if (-not $hasSecret) {
        Write-Host "[..] backend/.env has no SECRET_KEY; using a dev-only key for this session"
        $secretPrefix = "`$env:SECRET_KEY = 'dev-only-secret-key-min-32-chars-a7f3e2c8b4d9f1e6'; "
    }
    $bffCmd = "cd '$BackendDir'; $secretPrefix`$env:HEALTH_DOMAIN_MODE = 'postgres'; `$env:HEALTH_DOMAIN_URL = '$DomainUrl'; `$env:HEALTH_DOMAIN_TOKEN = '$DomainToken'; `$env:DATABASE_URL = 'sqlite:///./compass.db'; ..\.venv\Scripts\python.exe -m uvicorn main:app --reload"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $bffCmd
    if (-not (Wait-Http "http://localhost:8000/healthz" $null "FastAPI BFF (:8000)")) {
        throw "FastAPI failed to start - check its window for errors."
    }
} else {
    Write-Host "[OK] FastAPI already running (:8000)" -ForegroundColor Green
}

# -- 4. Static frontend -----------------------------------------------------
$feUp = $false
try { $feUp = (Invoke-WebRequest -Uri "http://localhost:5500" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch {}
if (-not $feUp) {
    $feCmd = "cd '$FrontendDir'; python -m http.server 5500"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $feCmd
    if (-not (Wait-Http "http://localhost:5500" $null "Frontend (:5500)")) {
        throw "Frontend static server failed to start."
    }
} else {
    Write-Host "[OK] Frontend already running (:5500)" -ForegroundColor Green
}

Write-Host ""
Write-Host "All stages healthy:" -ForegroundColor Cyan
Write-Host "  App:      http://localhost:5500"
Write-Host "  BFF:      http://localhost:8000/healthz"
Write-Host "  Domain:   $DomainUrl/api/health (service-auth)"
Write-Host "  Postgres: localhost:5433/compass_health"
Write-Host ""
Write-Host "Browser health requests now go through the BFF (M01). Legacy pages"
Write-Host "still served by FastAPI/SQLite until the M02 read-only switch."
