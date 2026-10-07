# ==============================================================================
# Check ServiceNow UAT Agent Local Services Status
# ==============================================================================
# Displays:
# - API process and health
# - Worker process
# - Frontend process
# - Redis connectivity
# - PostgreSQL connectivity
# - Configured runtime mode
# - Browser mode
# - Report and screenshot paths
# ==============================================================================

[CmdletBinding()]
param()

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  ServiceNow UAT Agent - Local Status Report" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$RuntimeDir = Join-Path $RepoRoot ".runtime\local"
$RedisPidFile = Join-Path $RuntimeDir "redis.pid"
$ApiPidFile = Join-Path $RuntimeDir "api.pid"
$WorkerPidFile = Join-Path $RuntimeDir "worker.pid"
$FrontendPidFile = Join-Path $RuntimeDir "frontend.pid"

function Check-ServiceProcess {
    param([string]$Name, [string]$PidFile, [int]$PortFallback = 0)

    if (Test-Path $PidFile) {
        $pidVal = (Get-Content $PidFile -ErrorAction SilentlyContinue).Trim()
        if ($pidVal) {
            $proc = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "  $Name`: RUNNING (PID: $pidVal, Memory: $([math]::Round($proc.WorkingSet64 / 1MB, 1)) MB)" -ForegroundColor Green
                return $true
            }
        }
    }

    if ($PortFallback -gt 0) {
        try {
            $conn = Get-NetTCPConnection -LocalPort $PortFallback -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($conn -and $conn.OwningProcess) {
                $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
                if ($proc) {
                    $conn.OwningProcess | Out-File -FilePath $PidFile -Encoding ascii -Force
                    Write-Host "  $Name`: RUNNING (PID: $($conn.OwningProcess), Memory: $([math]::Round($proc.WorkingSet64 / 1MB, 1)) MB)" -ForegroundColor Green
                    return $true
                }
            }
        } catch {}
    }

    Write-Host "  $Name`: STOPPED" -ForegroundColor Red
    return $false
}

$EnvLocal = Join-Path $RepoRoot ".env.local"
if (Test-Path $EnvLocal) {
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
}
$ApiPort = if ($env:API_PORT) { [int]$env:API_PORT } else { 8000 }

Write-Host "`n[Processes]" -ForegroundColor Yellow
$redisRunning = Check-ServiceProcess -Name "Redis    " -PidFile $RedisPidFile -PortFallback 6379
$apiRunning = Check-ServiceProcess -Name "API      " -PidFile $ApiPidFile -PortFallback $ApiPort
$workerRunning = Check-ServiceProcess -Name "Worker   " -PidFile $WorkerPidFile
$frontendRunning = Check-ServiceProcess -Name "Frontend " -PidFile $FrontendPidFile -PortFallback 5173

Write-Host "`n[API Health & Readiness]" -ForegroundColor Yellow
if ($apiRunning) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/v1/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
        Write-Host "  Liveness (/health):  $($health.status.ToUpper()) (v$($health.version))" -ForegroundColor Green
    } catch {
        Write-Host "  Liveness (/health):  UNRESPONSIVE ($($_.Exception.Message))" -ForegroundColor Red
    }

    try {
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/v1/ready" -Method Get -TimeoutSec 10 -ErrorAction Stop
        Write-Host "  Readiness (/ready):  $($ready.status.ToUpper())" -ForegroundColor Green
    } catch {
        if ($_.Exception.Response) {
            Write-Host "  Readiness (/ready):  NOT READY (Status $($_.Exception.Response.StatusCode.value__))" -ForegroundColor Yellow
        } else {
            Write-Host "  Readiness (/ready):  CHECK FAILED ($($_.Exception.Message))" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  API is not running." -ForegroundColor Gray
}

# Run Python diagnostic config
Write-Host "`n[Configuration Diagnostics]" -ForegroundColor Yellow
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$DiagScript = Join-Path $RepoRoot "scripts\diagnose_config.py"

if (Test-Path $DiagScript) {
    & $PythonExe $DiagScript
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
