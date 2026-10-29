$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
& '.venv/Scripts/npm.exe' ci --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'MathJax installation failed.' }
& '.venv/Scripts/python.exe' scripts/write_config.py
if ($LASTEXITCODE -ne 0) { throw 'MCP configuration generation failed.' }
Write-Host 'Ready. Run .\start.ps1 and open http://127.0.0.1:8765'
