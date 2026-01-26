$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

function Import-DotEnv {
    param([string]$EnvPath)
    if (-not (Test-Path $EnvPath)) { return }
    Get-Content $EnvPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path ("Env:" + $key) -Value $value
    }
}

Import-DotEnv (Join-Path $root ".env")

function Normalize-EnvPathList {
    param([string]$Value, [string]$Base)
    if (-not $Value) { return $Value }
    $sep = ";"
    $parts = $Value -split $sep
    $abs = foreach ($p in $parts) {
        if (-not $p) { continue }
        if ([System.IO.Path]::IsPathRooted($p)) { $p } else { Join-Path $Base $p }
    }
    return ($abs -join $sep)
}

if ($env:FS_ALLOWED_DIRS) {
    $env:FS_ALLOWED_DIRS = Normalize-EnvPathList $env:FS_ALLOWED_DIRS $root
}
if ($env:FILE_STORE_DIR -and -not [System.IO.Path]::IsPathRooted($env:FILE_STORE_DIR)) {
    $env:FILE_STORE_DIR = Join-Path $root $env:FILE_STORE_DIR
}

if ($env:FS_ALLOWED_DIRS) {
    ($env:FS_ALLOWED_DIRS -split ";") | ForEach-Object {
        if ($_ -and -not (Test-Path $_)) { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
    }
}
if ($env:FILE_STORE_DIR -and -not (Test-Path $env:FILE_STORE_DIR)) {
    New-Item -ItemType Directory -Force -Path $env:FILE_STORE_DIR | Out-Null
}

function Start-TrackedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -PassThru
    $pidPath = Join-Path $runDir "$Name.pid"
    Set-Content -Path $pidPath -Value $process.Id
    Write-Host "Started $Name (PID $($process.Id))"
}

$psExe = (Get-Command powershell).Source

$mcpScript = Join-Path $root "services\mcp-server\run_local.ps1"
Start-TrackedProcess -Name "mcp-server" -FilePath $psExe -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $mcpScript) -WorkingDirectory (Split-Path $mcpScript)

$hostScript = Join-Path $root "services\host-service\run_local.ps1"
Start-TrackedProcess -Name "host-service" -FilePath $psExe -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $hostScript) -WorkingDirectory (Split-Path $hostScript)

$dummyScript = Join-Path $root "services\dummy-api\run_local.ps1"
Start-TrackedProcess -Name "dummy-api" -FilePath $psExe -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $dummyScript) -WorkingDirectory (Split-Path $dummyScript)

$webDir = Join-Path $root "apps\web"
$webCommand = "cd `"$webDir`"; if (!(Test-Path node_modules)) { npm install }; npm run dev"
Start-TrackedProcess -Name "web" -FilePath $psExe -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $webCommand) -WorkingDirectory $webDir
