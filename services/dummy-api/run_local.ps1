$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Test-Path "..\..\.env") {
    Get-Content "..\..\.env" | ForEach-Object {
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
if (-not (Test-Path ".\\.venv")) { python -m venv .venv }
. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 9000
