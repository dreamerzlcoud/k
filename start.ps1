param([int]$Port = 8765, [int]$InferencePort = 8766)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run .\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath 'node_modules/mathjax-full')) { throw 'Run .\setup.ps1 first.' }
$env:PYTHONUTF8 = '1'
$env:INKLAB_INFERENCE_URL = "http://127.0.0.1:$InferencePort"
Start-Process -WindowStyle Hidden -FilePath '.venv/Scripts/python.exe' -ArgumentList "-m uvicorn inklab.inference_server:inference_app --host 127.0.0.1 --port $InferencePort"
Start-Process "http://127.0.0.1:$Port"
Write-Host "InkLab Web: http://127.0.0.1:$Port | AI Inference: http://127.0.0.1:$InferencePort (Ctrl+C to stop)"
& '.venv/Scripts/python.exe' -m uvicorn inklab.app:app --host 127.0.0.1 --port $Port
