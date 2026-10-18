@echo off
REM ═══════════════════════════════════════════════════════════
REM  Olmavax A.I — one-click launcher
REM  Starts the web app, and Olmavax Agent too if Python is present.
REM ═══════════════════════════════════════════════════════════
setlocal
cd /d "%~dp0"

echo.
echo   ██  Olmavax A.I  — starting...
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo   [X] Node.js was not found. Install Node 18+ from https://nodejs.org
  echo.
  pause
  exit /b 1
)

REM --- optional: Olmavax Agent sidecar ---
where python >nul 2>nul
if errorlevel 1 (
  echo   [i] Python not found - skipping Olmavax Agent. The app still works.
) else (
  echo   [+] Starting Olmavax Agent on http://127.0.0.1:8765 ...
  start "Olmavax Olmavax Agent" /min python advanced\Olmavax Agent\sidecar.py ui
  timeout /t 3 /nobreak >nul
)

echo   [+] Web app  →  http://127.0.0.1:8787
echo.
echo   Press Ctrl+C to stop.
echo.

node server\server.js

endlocal
