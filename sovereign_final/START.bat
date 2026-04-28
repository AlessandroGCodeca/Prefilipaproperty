@echo off
REM ══════════════════════════════════════════════════════
REM  Sovereign RE Dashboard — Windows Auto-Start
REM  Double-click this file, or add to Windows startup.
REM  Place this file in your sovereign_final\ folder.
REM ══════════════════════════════════════════════════════

echo Starting Sovereign Investor Dashboard...
echo.

REM Move to the project folder (edit this path)
cd /d "%~dp0"

REM Check Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo Docker is not running. Starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo Waiting 30 seconds for Docker to start...
    timeout /t 30 /nobreak >nul
)

REM Start all containers
echo Launching containers...
docker compose up -d

echo.
echo ✅ Sovereign Dashboard starting...
echo    Opening http://localhost:8501 in 15 seconds...
echo.
timeout /t 15 /nobreak >nul

REM Open browser
start http://localhost:8501

echo.
echo Dashboard is running at http://localhost:8501
echo Scheduler runs pipeline daily at 06:00 CET automatically.
echo Close this window when done (containers keep running).
echo.
pause
