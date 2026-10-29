param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run .\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath 'node_modules/mathjax-full')) { throw 'Run .\setup.ps1 first.' }
$env:PYTHONUTF8 = '1'
Write-Host "InkLab: http://127.0.0.1:$Port  (Ctrl+C to stop)"
& '.venv/Scripts/python.exe' -m uvicorn inklab.app:app --host 127.0.0.1 --port $Port
