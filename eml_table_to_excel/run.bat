@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

title EML Table to Excel

for %%I in ("%~dp0..\eml_attachment_tool\python\python.exe") do set "PYTHON_EXE=%%~fI"
for %%I in ("%~dp0..\eml_attachment_tool\setup_embedded_python.bat") do set "PYTHON_SETUP=%%~fI"

if not exist "%PYTHON_EXE%" (
    if not exist "%PYTHON_SETUP%" (
        echo [ERROR] Shared Embedded Python setup script was not found.
        echo Expected: %PYTHON_SETUP%
        pause
        exit /b 1
    )
    echo ==============================================================
    echo  Shared Embedded Python is not ready.
    echo  Preparing it through the existing EML Attachment Tool...
    echo ==============================================================
    call "%PYTHON_SETUP%"
    if errorlevel 1 (
        echo.
        echo [ERROR] Embedded Python setup failed.
        pause
        exit /b 1
    )
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Embedded Python was not found: %PYTHON_EXE%
    pause
    exit /b 1
)

echo [Runtime] %PYTHON_EXE%

if "%~1"=="" (
    "%PYTHON_EXE%" -X utf8 "%~dp0app.py"
) else (
    "%PYTHON_EXE%" -X utf8 "%~dp0app.py" "%~1"
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
