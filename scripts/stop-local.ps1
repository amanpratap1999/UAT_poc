# ==============================================================================
# Stop ServiceNow UAT Agent Local Processes
# ==============================================================================
# Stops ONLY the processes created by start-local.ps1
# Cleans up PID files
# Leaves PostgreSQL, Redis, and Docker running
# ==============================================================================

[CmdletBinding()]
param()

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  ServiceNow UAT Agent - Stopping Local Services" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$RuntimeDir = Join-Path $RepoRoot ".runtime\local"
$PidFiles = @{
    "API" = (Join-Path $RuntimeDir "api.pid")
    "Worker" = (Join-Path $RuntimeDir "worker.pid")
    "Frontend" = (Join-Path $RuntimeDir "frontend.pid")
}

function Stop-RecordedProcess {
    param(
        [string]$ServiceName,
        [string]$PidFilePath
    )

    if (-not (Test-Path $PidFilePath)) {
        Write-Host "  ${ServiceName}: No PID file found (not running or already stopped)."
        return
    }

    $pidVal = (Get-Content -Path $PidFilePath -ErrorAction SilentlyContinue).Trim()
    if (-not $pidVal) {
        Remove-Item -Path $PidFilePath -Force -ErrorAction SilentlyContinue
        return
    }

    try {
        $proc = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
        if ($proc) {
            # Stale PID guard: Ensure this process actually belongs to python/node/cmd/powershell
            $procName = $proc.ProcessName.ToLower()
            $allowedNames = @("python", "python3", "node", "cmd", "powershell", "pwsh")
            if (-not ($allowedNames -contains $procName)) {
                Write-Warning "  ${ServiceName}: PID $pidVal matches process '$procName' which is not an expected runner ($($allowedNames -join ', ')). Skipping taskkill to protect unrelated process."
                Remove-Item -Path $PidFilePath -Force -ErrorAction SilentlyContinue
                return
            }

            Write-Host "  Stopping $ServiceName (PID: $pidVal, Process: $($proc.ProcessName))..." -ForegroundColor Yellow
            
            # Kill process tree using taskkill to ensure child processes terminate cleanly
            & taskkill /PID $pidVal /T /F | Out-Null
            Start-Sleep -Milliseconds 500
            
            # Verify if still running
            $procAfter = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
            if ($procAfter) {
                Stop-Process -Id $pidVal -Force -ErrorAction SilentlyContinue
            }
            Write-Host "  $ServiceName stopped." -ForegroundColor Green
        } else {
            Write-Host "  ${ServiceName}: PID $pidVal is no longer running."
        }
    } catch {
        Write-Warning "  Error stopping $ServiceName (PID: $pidVal): $_"
    } finally {
        Remove-Item -Path $PidFilePath -Force -ErrorAction SilentlyContinue
    }
}

foreach ($name in $PidFiles.Keys) {
    Stop-RecordedProcess -ServiceName $name -PidFilePath $PidFiles[$name]
}

# Clean up pids.json if present
$PidsJson = Join-Path $RuntimeDir "pids.json"
if (Test-Path $PidsJson) {
    Remove-Item -Path $PidsJson -Force -ErrorAction SilentlyContinue
}

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  All local UAT Agent processes have been stopped." -ForegroundColor Green
Write-Host "  (PostgreSQL and Redis system services were left running)" -ForegroundColor Gray
Write-Host "=================================================================" -ForegroundColor Cyan
