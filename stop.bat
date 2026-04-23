@echo off
echo Stopping Compass Health...

REM Kill process listening on port 8000 (backend)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)

REM Kill process listening on port 5500 (frontend)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5500 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo Done.
