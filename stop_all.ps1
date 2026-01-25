$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root ".run"

function Stop-ByPidFile {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )

    $pidPath = Join-Path $runDir "$Name.pid"
    if (-not (Test-Path $pidPath)) {
        return
    }

    $processId = Get-Content $pidPath -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($processId) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $Name (PID $processId)"
    }

    Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
}

function Stop-ByPort {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($connection -and $connection.OwningProcess) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $Name (Port $Port, PID $($connection.OwningProcess))"
    }
}

Stop-ByPidFile -Name "web"
Stop-ByPidFile -Name "host-service"
Stop-ByPidFile -Name "mcp-server"

Stop-ByPort -Port 3000 -Name "web"
Stop-ByPort -Port 8080 -Name "host-service"
Stop-ByPort -Port 8000 -Name "mcp-server"
