$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Test-Path "..\\..\\.env") {
    Get-Content "..\\..\\.env" | ForEach-Object {
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

$repoRoot = Resolve-Path "..\\.."
if ($env:FS_ALLOWED_DIRS) {
    $parts = $env:FS_ALLOWED_DIRS -split ";"
    $abs = foreach ($p in $parts) {
        if (-not $p) { continue }
        if ([System.IO.Path]::IsPathRooted($p)) { $p } else { Join-Path $repoRoot $p }
    }
    $env:FS_ALLOWED_DIRS = ($abs -join ";")
}
if ($env:FILE_STORE_DIR -and -not [System.IO.Path]::IsPathRooted($env:FILE_STORE_DIR)) {
    $env:FILE_STORE_DIR = Join-Path $repoRoot $env:FILE_STORE_DIR
}

if ($env:FS_ALLOWED_DIRS) {
    ($env:FS_ALLOWED_DIRS -split ";") | ForEach-Object {
        if ($_ -and -not (Test-Path $_)) { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
    }
}
if ($env:FILE_STORE_DIR -and -not (Test-Path $env:FILE_STORE_DIR)) {
    New-Item -ItemType Directory -Force -Path $env:FILE_STORE_DIR | Out-Null
}
if (-not $env:FS_MCP_ENABLED) { $env:FS_MCP_ENABLED = "true" }
if (-not (Test-Path ".\\.venv")) { python -m venv .venv }
. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not $env:HOST_PORT) { $env:HOST_PORT = "8080" }
uvicorn app:app --host 0.0.0.0 --port $env:HOST_PORT
