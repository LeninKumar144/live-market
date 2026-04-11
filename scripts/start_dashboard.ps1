# Start API + Vite dashboard, then open Chrome.
# Run:  powershell -ExecutionPolicy Bypass -File scripts\start_dashboard.ps1
# From repo root:  marketanalyze\

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

Write-Host "Starting FastAPI on http://127.0.0.1:8000 ..."
Start-Process powershell -WorkingDirectory $Backend -ArgumentList @(
    "-NoExit", "-Command", "python -m uvicorn main:app --host 127.0.0.1 --port 8000"
)

Start-Sleep -Seconds 2

Write-Host "Starting Vite on http://127.0.0.1:5173 ..."
Start-Process powershell -WorkingDirectory $Frontend -ArgumentList @(
    "-NoExit", "-Command", "npm run dev"
)

Start-Sleep -Seconds 5

Write-Host "Opening Chrome..."
$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
if (Test-Path $chrome) {
    Start-Process $chrome "http://127.0.0.1:5173"
} else {
    Start-Process "http://127.0.0.1:5173"
}

Write-Host "Done. Leave the two PowerShell windows open while you use the dashboard."
