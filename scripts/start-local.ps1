# ==============================================================================
# Start ServiceNow UAT Agent Locally
# ==============================================================================
# Starts FastAPI API, Celery worker (threads pool), and React/Vite frontend
# Records created process PIDs in .runtime/local/
# Writes separate logs to logs/*.local.log
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$VisibleWindows,
    [switch]$Foreground,
    [switch]$SkipInitDb,
    [switch]$NoBrowser,
    [switch]$SkipReadinessCheck
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  ServiceNow UAT Agent - Local Runtime Startup" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# 1. Load .env.local
$EnvLocal = Join-Path $RepoRoot ".env.local"
if (-not (Test-Path $EnvLocal)) {
    Write-Warning ".env.local not found. Looking for .env..."
    $EnvFallback = Join-Path $RepoRoot ".env"
    if (Test-Path $EnvFallback) {
        $EnvLocal = $EnvFallback
    } else {
        Write-Error "No environment configuration found. Run .\scripts\bootstrap-local.ps1 first."
        exit 1
    }
}

Write-Host "Loading environment from $EnvLocal..."
Get-Content $EnvLocal | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line -match "^([^=]+)=(.*)$") {
        $key = $matches[1].Trim()
        $val = $matches[2].Trim().Trim('"').Trim("'")
        if (-not [string]::IsNullOrEmpty($key)) {
            [System.Environment]::SetEnvironmentVariable($key, $val, [System.EnvironmentVariableTarget]::Process)
        }
    }
}

# Ensure local runtime mode
$env:UAT_RUNTIME_MODE = "local"
$env:UAT_ENV_FILE = $EnvLocal

$ApiPort = if ($env:API_PORT) { [int]$env:API_PORT } else { 8000 }

# 2. Set PYTHONPATH to src
$SrcDir = Join-Path $RepoRoot "src"
$env:PYTHONPATH = $SrcDir
Write-Host "PYTHONPATH set to $SrcDir"

# 3. Interpreter resolution
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
Write-Host "Using Python interpreter: $PythonExe"

# Ensure runtime and log directories exist
$RuntimeDir = Join-Path $RepoRoot ".runtime\local"
$LogsDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $RepoRoot "reports") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $RepoRoot "screenshots") -Force | Out-Null

# 3.5 Ensure local Redis is running
$RedisExe = Join-Path $RepoRoot ".bin\redis\redis-server.exe"
$redisListening = $false
try {
    $rconn = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($rconn) { $redisListening = $true }
} catch {}

if (-not $redisListening -and (Test-Path $RedisExe)) {
    Write-Host "`nStarting local Redis server (127.0.0.1:6379)..." -ForegroundColor Yellow
    $RedisLog = Join-Path $LogsDir "redis.local.log"
    $RedisPidFile = Join-Path $RuntimeDir "redis.pid"
    $redisProcess = Start-Process -FilePath $RedisExe `
        -RedirectStandardOutput $RedisLog `
        -RedirectStandardError (Join-Path $LogsDir "redis.err.local.log") `
        -WindowStyle Hidden `
        -PassThru
    $redisProcess.Id | Out-File -FilePath $RedisPidFile -Encoding ascii -Force
    Start-Sleep -Seconds 1
    Write-Host "  Redis started with PID: $($redisProcess.Id)" -ForegroundColor Green
}

# 4. Optional Database initialization
if (-not $SkipInitDb) {
    Write-Host "`n[1/4] Running database initialization (scripts/init_db.py)..." -ForegroundColor Yellow
    $InitDbScript = Join-Path $RepoRoot "scripts\init_db.py"
    try {
        & $PythonExe $InitDbScript
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Database initialized successfully." -ForegroundColor Green
        } else {
            Write-Warning "  init_db.py returned code $LASTEXITCODE. Database may be uninitialized or unreachable."
        }
    } catch {
        Write-Warning "  init_db.py skipped or failed: $_"
    }
} else {
    Write-Host "`n[1/4] Skipping database initialization (-SkipInitDb flag)." -ForegroundColor Yellow
}

# 5. Start API locally
Write-Host "`n[2/4] Starting FastAPI API (http://127.0.0.1:$ApiPort)..." -ForegroundColor Yellow
$ApiLog = Join-Path $LogsDir "api.local.log"
$ApiPidFile = Join-Path $RuntimeDir "api.pid"

if (Test-Path $ApiPidFile) {
    $existingPid = (Get-Content $ApiPidFile -ErrorAction SilentlyContinue).Trim()
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Warning "API is already running with PID $existingPid"
    } else {
        Remove-Item $ApiPidFile -Force -ErrorAction SilentlyContinue
    }
}

$apiProcess = $null
if ($VisibleWindows) {
    $apiCmd = "`$env:PYTHONPATH='$SrcDir'; `$env:UAT_RUNTIME_MODE='local'; `$env:UAT_ENV_FILE='$EnvLocal'; & '$PythonExe' -m uvicorn agent.main:app --host 127.0.0.1 --port $ApiPort --reload 2>&1 | Tee-Object -FilePath '$ApiLog'"
    $apiProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd -PassThru
} else {
    $apiProcess = Start-Process -FilePath $PythonExe `
        -ArgumentList "-m", "uvicorn", "agent.main:app", "--host", "127.0.0.1", "--port", "$ApiPort", "--reload" `
        -RedirectStandardOutput $ApiLog `
        -RedirectStandardError (Join-Path $LogsDir "api.err.local.log") `
        -WindowStyle Hidden `
        -PassThru
}

$apiProcess.Id | Out-File -FilePath $ApiPidFile -Encoding ascii -Force
Write-Host "  API process started with PID: $($apiProcess.Id)" -ForegroundColor Green

# 8. Wait for API health before starting worker and frontend
Write-Host "  Waiting for API health at http://127.0.0.1:$ApiPort/api/v1/health..."
$maxAttempts = 30
$attempt = 0
$apiHealthy = $false

while ($attempt -lt $maxAttempts) {
    Start-Sleep -Seconds 1
    $attempt++
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/v1/health" -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($response -and $response.status -eq "healthy") {
            $apiHealthy = $true
            break
        }
    } catch {
        # Retry
    }
}

if (-not $apiHealthy) {
    Write-Error "API failed to report healthy after $maxAttempts seconds. Check log at $ApiLog."
    & (Join-Path $PSScriptRoot "stop-local.ps1")
    exit 1
}
Write-Host "  API is HEALTHY!" -ForegroundColor Green

# Check API readiness probe (fail fast if backing services are offline unless -SkipReadinessCheck is specified)
try {
    $readyRes = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/v1/ready" -Method Get -TimeoutSec 5 -ErrorAction Stop
    if ($readyRes.status -eq "ready") {
        Write-Host "  Readiness check: READY (Postgres, Redis, Dirs, Embedding OK)" -ForegroundColor Green
    } else {
        if (-not $SkipReadinessCheck) {
            Write-Error "  API readiness failed: status='$($readyRes.status)'. Backing services are not ready. Use -SkipReadinessCheck to bypass."
            & (Join-Path $PSScriptRoot "stop-local.ps1")
            exit 1
        } else {
            Write-Warning "  Readiness check reported not_ready (bypassed via -SkipReadinessCheck)."
        }
    }
} catch {
    if (-not $SkipReadinessCheck) {
        Write-Error "  Readiness check failed: $_. Backing services (PostgreSQL/Redis) appear unreachable. Use -SkipReadinessCheck to bypass."
        & (Join-Path $PSScriptRoot "stop-local.ps1")
        exit 1
    } else {
        Write-Warning "  Readiness check could not verify all dependencies (bypassed via -SkipReadinessCheck)."
    }
}

# 6. Start Celery worker locally using solo pool (Windows-compatible)
Write-Host "`n[3/4] Starting Celery worker (pool=solo)..." -ForegroundColor Yellow
$WorkerLog = Join-Path $LogsDir "worker.local.log"
$WorkerPidFile = Join-Path $RuntimeDir "worker.pid"

$workerProcess = $null
if ($VisibleWindows) {
    # P1.6: Celery Concurrency Documentation
    # Playwright headed browsers are stateful and tightly coupled to the OS GUI session. 
    # Using thread/gevent pools will cause asyncio/event loop conflicts with Playwright.
    # Using prefork (multiprocessing) on Windows causes issues with GUI focus and zombie Chromium processes.
    # Therefore, --pool=solo is enforced to ensure 1:1 binding between the worker process and the browser window.
    $workerCmd = "`$env:PYTHONPATH='$SrcDir'; `$env:UAT_RUNTIME_MODE='local'; `$env:UAT_ENV_FILE='$EnvLocal'; & '$PythonExe' -m celery -A agent.core.celery_app worker --loglevel=info --pool=solo 2>&1 | Tee-Object -FilePath '$WorkerLog'"
    $workerProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", $workerCmd -PassThru
} else {
    $workerWindowStyle = if ($env:BROWSER_HEADLESS -eq "false") { "Minimized" } else { "Hidden" }
    $workerProcess = Start-Process -FilePath $PythonExe `
        -ArgumentList "-m", "celery", "-A", "agent.core.celery_app", "worker", "--loglevel=info", "--pool=solo" `
        -RedirectStandardOutput $WorkerLog `
        -RedirectStandardError (Join-Path $LogsDir "worker.err.local.log") `
        -WindowStyle $workerWindowStyle `
        -PassThru
}

Start-Sleep -Milliseconds 600
if ($workerProcess.HasExited) {
    Write-Error "  Celery worker process exited unexpectedly with code $($workerProcess.ExitCode). Check log at $WorkerLog."
    & (Join-Path $PSScriptRoot "stop-local.ps1")
    exit 1
}

$workerProcess.Id | Out-File -FilePath $WorkerPidFile -Encoding ascii -Force
Write-Host "  Celery worker process started with PID: $($workerProcess.Id)" -ForegroundColor Green

# 7. Start React/Vite Frontend locally
Write-Host "`n[4/4] Starting Frontend dev server (http://127.0.0.1:5173)..." -ForegroundColor Yellow
$FrontendLog = Join-Path $LogsDir "frontend.local.log"
$FrontendPidFile = Join-Path $RuntimeDir "frontend.pid"
$FrontendDir = Join-Path $RepoRoot "frontend"

$frontendProcess = $null
if ($VisibleWindows) {
    $feCmd = "Set-Location '$FrontendDir'; npm run dev -- --host 127.0.0.1 --port 5173 2>&1 | Tee-Object -FilePath '$FrontendLog'"
    $frontendProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", $feCmd -PassThru
} else {
    $frontendProcess = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "cd /d `"$FrontendDir`" && npm run dev -- --host 127.0.0.1 --port 5173" `
        -RedirectStandardOutput $FrontendLog `
        -RedirectStandardError (Join-Path $LogsDir "frontend.err.local.log") `
        -WindowStyle Hidden `
        -PassThru
}

Start-Sleep -Milliseconds 600
if ($frontendProcess.HasExited) {
    Write-Error "  Frontend dev server process exited unexpectedly with code $($frontendProcess.ExitCode). Check log at $FrontendLog."
    & (Join-Path $PSScriptRoot "stop-local.ps1")
    exit 1
}

$frontendProcess.Id | Out-File -FilePath $FrontendPidFile -Encoding ascii -Force
Write-Host "  Frontend process started with PID: $($frontendProcess.Id)" -ForegroundColor Green

# 9. Store PIDs JSON record
$pidsData = @{
    api = $apiProcess.Id
    worker = $workerProcess.Id
    frontend = $frontendProcess.Id
    started_at = (Get-Date).ToString("o")
} | ConvertTo-Json

Set-Content -Path (Join-Path $RuntimeDir "pids.json") -Value $pidsData -Force

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host "  Local Application Started Successfully!" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "URLs:"
Write-Host "  Frontend:  http://localhost:5173" -ForegroundColor Yellow
Write-Host "  API:       http://localhost:$ApiPort"
Write-Host "  Health:    http://localhost:$ApiPort/api/v1/health"
Write-Host "  Readiness: http://localhost:$ApiPort/api/v1/ready"
Write-Host "`nLogs:"
Write-Host "  API:       $ApiLog"
Write-Host "  Worker:    $WorkerLog"
Write-Host "  Frontend:  $FrontendLog"
Write-Host "`nTo stop all processes: .\scripts\stop-local.ps1"
Write-Host "To check status:       .\scripts\status-local.ps1"

if (-not $NoBrowser) {
    Start-Process "http://localhost:5173" -ErrorAction SilentlyContinue
}

if ($Foreground) {
    Write-Host "`nRunning in foreground mode. Press Ctrl+C to stop services..." -ForegroundColor Cyan
    try {
        while ($true) {
            Start-Sleep -Seconds 2
            if (-not (Get-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue)) {
                Write-Warning "API process terminated."
                break
            }
        }
    } finally {
        & (Join-Path $PSScriptRoot "stop-local.ps1")
    }
}

