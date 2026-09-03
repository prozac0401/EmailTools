@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PY_VERSION=3.13.15"
set "PY_ZIP=python-%PY_VERSION%-embed-amd64.zip"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/%PY_ZIP%"
set "PY_DIR=%~dp0python"
set "LOCAL_ZIP=%~dp0%PY_ZIP%"
set "TMP_ZIP=%TEMP%\EmailTools-%RANDOM%-%RANDOM%-%PY_ZIP%.tmp"
set "PY_SOURCE="
set "DOWNLOADED="

if exist "%PY_DIR%\python.exe" (
    echo [OK] Embedded Python already exists: %PY_DIR%\python.exe
    exit /b 0
)

if not exist "%PY_DIR%" mkdir "%PY_DIR%"
if errorlevel 1 (
    echo [ERROR] Failed to create Python directory: %PY_DIR%
    exit /b 1
)

rem Prefer a pre-staged zip next to this BAT for fully offline deployment.
if exist "%LOCAL_ZIP%" (
    echo [1/2] Using local embedded Python package: %PY_ZIP%
    set "PY_SOURCE=%LOCAL_ZIP%"
) else (
    echo [1/2] Downloading official Python %PY_VERSION% embeddable x64 package...
    where curl.exe >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] curl.exe is unavailable.
        echo Put %PY_ZIP% next to setup_embedded_python.bat and retry.
        exit /b 1
    )
    curl.exe -fL --retry 3 --connect-timeout 15 -o "%TMP_ZIP%" "%PY_URL%"
    if errorlevel 1 (
        echo [ERROR] Download failed: %PY_URL%
        echo You can manually place %PY_ZIP% next to this BAT and retry.
        del /q "%TMP_ZIP%" >nul 2>nul
        exit /b 1
    )
    set "PY_SOURCE=%TMP_ZIP%"
    set "DOWNLOADED=1"
)

where tar.exe >nul 2>nul
if errorlevel 1 (
    echo [ERROR] tar.exe is unavailable. Windows 10/11 built-in tar.exe is required.
    if defined DOWNLOADED del /q "%TMP_ZIP%" >nul 2>nul
    exit /b 1
)

echo [2/2] Extracting into: %PY_DIR%
tar.exe -xf "%PY_SOURCE%" -C "%PY_DIR%"
if errorlevel 1 (
    echo [ERROR] Extraction failed.
    if defined DOWNLOADED del /q "%TMP_ZIP%" >nul 2>nul
    exit /b 1
)

if defined DOWNLOADED del /q "%TMP_ZIP%" >nul 2>nul

if not exist "%PY_DIR%\python.exe" (
    echo [ERROR] python.exe was not created.
    exit /b 1
)

echo [OK] Embedded Python ready: %PY_DIR%\python.exe
exit /b 0
