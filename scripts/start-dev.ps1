# Start backend (uvicorn :8000) and frontend (Vite :5173) for RFI crosscheck UI.
# Usage:
#   .\scripts\start-dev.ps1              # backend in new window, frontend here
#   .\scripts\start-dev.ps1 -SingleWindow  # both in this window (Ctrl+C stops both)

param(
    [switch]$SingleWindow,
    [switch]$SkipInstall,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Info($msg) { Write-Host $msg -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Warn($msg) { Write-Host $msg -ForegroundColor Yellow }

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$venvUvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"
$frontendDir = Join-Path $Root "frontend"

if (-not $SkipInstall) {
    if (-not (Test-Path $venvPython)) {
        Write-Info "Creating Python venv..."
        python -m venv .venv
    }
    Write-Info "Installing Python dependencies..."
    & $venvPython -m pip install -q -r requirements.txt

    if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
        Write-Info "Installing frontend dependencies..."
        Push-Location $frontendDir
        npm install
        Pop-Location
    }
}

if (-not (Test-Path $venvUvicorn)) {
    throw "uvicorn not found. Run: pip install -r requirements.txt"
}

function Wait-Backend {
    param([int]$Port, [int]$TimeoutSec = 45)
    $url = "http://127.0.0.1:$Port/health"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

$backendArgs = @(
    "backend.main:app",
    "--reload",
    "--host", "127.0.0.1",
    "--port", "$BackendPort"
)

$backendProc = $null

try {
    if ($SingleWindow) {
        Write-Info "Starting backend on port $BackendPort (background process)..."
        $backendProc = Start-Process -FilePath $venvUvicorn `
            -ArgumentList $backendArgs `
            -WorkingDirectory $Root `
            -PassThru `
            -WindowStyle Hidden
    } else {
        Write-Info "Starting backend on port $BackendPort (new window)..."
        $backendCmd = "Set-Location '$Root'; & '$venvUvicorn' $($backendArgs -join ' ')"
        $backendProc = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-NoExit", "-Command", $backendCmd `
            -PassThru
    }

    Write-Info "Waiting for backend health check..."
    if (-not (Wait-Backend -Port $BackendPort)) {
        throw "Backend did not become ready on port $BackendPort. Check backend logs."
    }
    Write-Ok "Backend ready: http://127.0.0.1:$BackendPort"

    Write-Info "Starting frontend on port $FrontendPort..."
    Write-Ok "Open http://localhost:$FrontendPort"
    if ($SingleWindow) {
        Write-Warn "Press Ctrl+C to stop frontend and backend."
    } else {
        Write-Warn "Press Ctrl+C to stop the frontend. Close the backend window or run scripts\stop-dev.ps1."
    }

    Push-Location $frontendDir
    $env:VITE_BACKEND_PORT = "$BackendPort"
    # Port/host are set in vite.config.js — npm 10+ treats --host/--port as npm flags if passed here.
    npm run dev
} finally {
    Pop-Location -ErrorAction SilentlyContinue

    if ($SingleWindow -and $backendProc -and -not $backendProc.HasExited) {
        Write-Info "Stopping backend..."
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
}
