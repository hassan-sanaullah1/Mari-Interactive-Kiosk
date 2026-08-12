# Launch the MARI · Voice front-end (sleek tap-to-speak UI) on Windows.
# Prefers the Python 3.12 venv (.venv312) if present — that's where Kokoro (English
# TTS) installs cleanly. Falls back to the system `python` otherwise.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$H = if ($env:MARI_HOST) { $env:MARI_HOST } else { "127.0.0.1" }
$P = if ($env:MARI_PORT) { $env:MARI_PORT } else { "8010" }

# Prefer a Python 3.12 venv with Kokoro. It lives at a SHORT path (C:\mv312) to dodge
# Windows' 260-char limit when installing torch. Override with $env:MARI_PYTHON.
$candidates = @($env:MARI_PYTHON, "C:\mv312\Scripts\python.exe",
                (Join-Path (Get-Location) ".venv312\Scripts\python.exe"))
$py = "python"
foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $py = $c; break } }

Write-Host "MARI - Voice  ->  http://${H}:${P}   (python: $py)"
& $py -m uvicorn server.app:app --host $H --port $P
