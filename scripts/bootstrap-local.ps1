# ==============================================================================
# Bootstrap Local Environment for ServiceNow UAT Agent
# ==============================================================================
# Requires: Windows PowerShell 5.1+ or PowerShell 7+
# Verifies Python >= 3.11, Node.js, npm
# Sets up .venv, backend dependencies, Playwright Chromium, frontend node_modules
# Initializes directories and .env.local
# ==============================================================================

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  ServiceNow UAT Agent - Local Environment Bootstrap" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "Repository root: $RepoRoot"

# 1. Verify Python 3.11 or newer
Write-Host "`n[1/7] Checking Python version..." -ForegroundColor Yellow
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Error "Python was not found in PATH. Please install Python 3.11 or newer from https://www.python.org/downloads/windows/"
    exit 1
}

$PyVerRaw = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
$PyVerMajor = & python -c "import sys; print(sys.version_info.major)"
$PyVerMinor = & python -c "import sys; print(sys.version_info.minor)"

if ([int]$PyVerMajor -lt 3 -or ([int]$PyVerMajor -eq 3 -and [int]$PyVerMinor -lt 11)) {
    Write-Error "Python 3.11 or newer is required. Found Python $PyVerRaw at $($PythonCmd.Source)"
    exit 1
}
Write-Host "  OK: Found Python $PyVerRaw ($($PythonCmd.Source))" -ForegroundColor Green

# 2. Verify Node.js and npm
Write-Host "`n[2/7] Checking Node.js and npm..." -ForegroundColor Yellow
$NodeCmd = Get-Command node -ErrorAction SilentlyContinue
$NpmCmd = Get-Command npm -ErrorAction SilentlyContinue

if (-not $NodeCmd) {
    Write-Error "Node.js was not found in PATH. Please install Node.js (v18+) from https://nodejs.org/"
    exit 1
}
if (-not $NpmCmd) {
    Write-Error "npm was not found in PATH. Please install Node.js with npm from https://nodejs.org/"
    exit 1
}

$NodeVer = & node -v
$NpmVer = & npm -v
Write-Host "  OK: Node.js $NodeVer ($($NodeCmd.Source))" -ForegroundColor Green
Write-Host "  OK: npm $NpmVer ($($NpmCmd.Source))" -ForegroundColor Green

# 3. Create .venv if missing
Write-Host "`n[3/7] Setting up Python virtual environment (.venv)..." -ForegroundColor Yellow
$VenvPath = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "  Creating virtual environment at $VenvPath..."
    & python -m venv $VenvPath
    if (-not (Test-Path $VenvPython)) {
        Write-Error "Failed to create virtual environment at $VenvPath"
        exit 1
    }
    Write-Host "  Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "  Existing virtual environment found at $VenvPath" -ForegroundColor Green
}

# 4. Install backend dependencies
Write-Host "`n[4/7] Installing backend dependencies (pip install -e '.[dev]')..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install backend dependencies."
    exit $LASTEXITCODE
}
Write-Host "  Backend dependencies installed successfully." -ForegroundColor Green

# 5. Install Playwright Chromium
Write-Host "`n[5/7] Installing Playwright Chromium browser..." -ForegroundColor Yellow
& $VenvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Playwright Chromium browser."
    exit $LASTEXITCODE
}
Write-Host "  Playwright Chromium installed successfully." -ForegroundColor Green

# 6. Install frontend dependencies
Write-Host "`n[6/7] Installing frontend dependencies (npm ci)..." -ForegroundColor Yellow
$FrontendDir = Join-Path $RepoRoot "frontend"
Push-Location $FrontendDir
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "npm ci encountered an issue, attempting npm install..."
        & npm install
    }
    Write-Host "  Frontend dependencies installed successfully." -ForegroundColor Green
} finally {
    Pop-Location
}

# 7. Create output directories and template initialization
Write-Host "`n[7/7] Creating required directories and local configuration..." -ForegroundColor Yellow
$Dirs = @(
    (Join-Path $RepoRoot "reports"),
    (Join-Path $RepoRoot "screenshots"),
    (Join-Path $RepoRoot "logs"),
    (Join-Path $RepoRoot ".runtime\local")
)

foreach ($dir in $Dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  Created directory: $dir"
    } else {
        Write-Host "  Directory exists: $dir"
    }
}

$EnvLocal = Join-Path $RepoRoot ".env.local"
$EnvLocalExample = Join-Path $RepoRoot ".env.local.example"

if (-not (Test-Path $EnvLocal)) {
    if (Test-Path $EnvLocalExample) {
        Copy-Item -Path $EnvLocalExample -Destination $EnvLocal
        Write-Host "  Created .env.local from .env.local.example" -ForegroundColor Green
        Write-Host "  NOTE: Edit .env.local to configure your real credentials." -ForegroundColor Cyan
    } else {
        Write-Warning "Cannot find .env.local.example to copy."
    }
} else {
    Write-Host "  Preserving existing .env.local (will never overwrite)." -ForegroundColor Green
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host "  Bootstrap Complete!" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "Next steps:"
Write-Host "  1. Verify/update your settings in .env.local"
Write-Host "  2. Run '.\scripts\check-local-services.ps1' to test PostgreSQL and Redis"
Write-Host "  3. Run '.\scripts\start-local.ps1' to start the application"
