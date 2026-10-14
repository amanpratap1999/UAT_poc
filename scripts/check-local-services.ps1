# ==============================================================================
# Check Local Services for ServiceNow UAT Agent
# ==============================================================================
# Validates PostgreSQL, Redis, Port 8000, Port 5173, and Playwright Chromium
# Never starts Docker silently
# ==============================================================================

[CmdletBinding()]
param()

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

$CheckScript = Join-Path $RepoRoot "scripts\check_services.py"

& $PythonExe $CheckScript
exit $LASTEXITCODE
