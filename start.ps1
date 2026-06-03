# ─── CUTM AI — Start Script ──────────────────────────────────────────────────
# Run this script from PowerShell to start the server cleanly.
# Usage: cd "d:\botai"; .\start.ps1

Write-Host "🛑 Stopping any existing Python servers..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

Write-Host "🚀 Starting CUTM AI Server..." -ForegroundColor Cyan
& "d:\botai\botai\.venv\Scripts\python.exe" "d:\botai\botai\simple_server.py"
