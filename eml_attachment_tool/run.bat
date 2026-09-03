@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

title EML Attachment Tool

if not exist "%~dp0python\python.exe" (
    echo ==============================================================
    echo  Local Embedded Python is not ready.
    echo  Preparing Python inside this program folder...
    echo ==============================================================
    call "%~dp0setup_embedded_python.bat"
    if errorlevel 1 (
        echo.
        echo [ERROR] Embedded Python setup failed.
        pause
        exit /b 1
    )
)

if not exist "%~dp0python\python.exe" (
    echo [ERROR] python\python.exe was not found.
    pause
    exit /b 1
)

echo [Runtime] %~dp0python\python.exe

if "%~1"=="" (
    "%~dp0python\python.exe" -X utf8 "%~dp0app.py"
) else (
    "%~dp0python\python.exe" -X utf8 "%~dp0app.py" "%~1"
)

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo [OK] 작업이 끝났습니다.
) else (
    echo [ERROR] 종료 코드: %RC%
)
pause
exit /b %RC%
