# ─── CUTM AI — Start Script ──────────────────────────────────────────────────
# Run this script from PowerShell to start the server cleanly.
# Usage: cd "d:\BOT AI"; .\start.ps1

Write-Host "🛑 Stopping any existing Python servers..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

Write-Host "🚀 Starting CUTM AI Server..." -ForegroundColor Cyan
& "d:\BOT AI\BOT AI\.venv\Scripts\python.exe" "d:\BOT AI\BOT AI\simple_server.py"
