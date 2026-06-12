# Stop processes listening on dev ports (default 8000 backend, 5173 frontend).
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

function Stop-PortListeners {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $procId = $c.OwningProcess
        if ($procId -and $procId -ne 0) {
            Write-Host "Stopping PID $procId on port $Port"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

Stop-PortListeners -Port $BackendPort
Stop-PortListeners -Port $FrontendPort
Write-Host "Done."
