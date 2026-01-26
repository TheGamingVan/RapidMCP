$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".\\.venv")) { python -m venv .venv }
. .\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 9000
