@echo off
cd /d "%~dp0"

echo ============================================
echo   Compass Health - Starting...
echo ============================================
echo.

REM Start backend in a new window
start "Compass Health - Backend" cmd /k "cd /d %~dp0backend && uvicorn main:app --reload"

REM Give the backend a moment to initialize
timeout /t 2 /nobreak >nul

REM Start frontend static server in a new window
start "Compass Health - Frontend" cmd /k "cd /d %~dp0frontend && python -m http.server 5500"

REM Give the frontend server a moment to start
timeout /t 1 /nobreak >nul

REM Open the app in the default browser
start http://localhost:5500

echo.
echo  Compass Health is running!
echo.
echo   App:      http://localhost:5500
echo   API:      http://localhost:8000
echo   API docs: http://localhost:8000/docs
echo.
echo  Close the Backend and Frontend windows to stop.
echo ============================================
