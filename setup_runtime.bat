@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PY_VERSION=3.13.15"
set "PY_ZIP=python-%PY_VERSION%-embed-amd64.zip"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/%PY_ZIP%"
for %%I in ("%~dp0runtime") do set "RUNTIME_DIR=%%~fI"
set "PY_DIR=%RUNTIME_DIR%\python"
set "LOCAL_ZIP=%~dp0%PY_ZIP%"
set "TMP_ZIP=%TEMP%\EmailTools-%RANDOM%-%RANDOM%-%PY_ZIP%.tmp"
set "PY_STAGE=%RUNTIME_DIR%\.python-setup-%RANDOM%-%RANDOM%"
set "PY_BACKUP=%RUNTIME_DIR%\.python-previous-%RANDOM%-%RANDOM%"
set "DOWNLOADED="
set "RC=1"

if exist "%PY_DIR%\python.exe" goto verify_installed
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
if errorlevel 1 exit /b 1
mkdir "%RUNTIME_DIR%\.setup-lock" 2>nul
if errorlevel 1 (
    echo [ERROR] Another runtime setup is active, or runtime is not writable.
    exit /b 1
)
if exist "%PY_STAGE%" goto cleanup
mkdir "%PY_STAGE%"
if errorlevel 1 goto cleanup
echo EmailTools runtime staging>"%PY_STAGE%\.emailtools-runtime"

rem Upgrade offline. Keep the old runtime as a backup; all launches use the new one.
if exist "%~dp0eml_attachment_tool\python\python.exe" (
    echo [Runtime] Reusing the existing embedded runtime...
    xcopy "%~dp0eml_attachment_tool\python\*" "%PY_STAGE%\" /E /I /Y >nul
    if errorlevel 1 goto cleanup
    goto publish
)
if not exist "%LOCAL_ZIP%" if exist "%~dp0eml_attachment_tool\%PY_ZIP%" set "LOCAL_ZIP=%~dp0eml_attachment_tool\%PY_ZIP%"
if exist "%LOCAL_ZIP%" (
    set "PY_SOURCE=%LOCAL_ZIP%"
) else (
    echo [1/2] Downloading official Python %PY_VERSION% embeddable x64 package...
    where curl.exe >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Put %PY_ZIP% next to setup_runtime.bat for offline setup.
        goto cleanup
    )
    set "DOWNLOADED=1"
    curl.exe -fL --retry 3 --connect-timeout 15 -o "%TMP_ZIP%" "%PY_URL%"
    if errorlevel 1 (
        echo [ERROR] Download failed. Put %PY_ZIP% next to setup_runtime.bat and retry.
        goto cleanup
    )
    set "PY_SOURCE=%TMP_ZIP%"
)
where tar.exe >nul 2>nul
if errorlevel 1 goto extraction_failed
echo [2/2] Preparing embedded Python...
tar.exe -xf "%PY_SOURCE%" -C "%PY_STAGE%"
if errorlevel 1 goto extraction_failed

:publish
if not exist "%PY_STAGE%\python.exe" goto extraction_failed
"%PY_STAGE%\python.exe" -I -c "import sys,ssl,ctypes,zipfile; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto extraction_failed
if exist "%PY_DIR%\" (
    if exist "%PY_BACKUP%" goto cleanup
    move "%PY_DIR%" "%PY_BACKUP%" >nul
    if errorlevel 1 goto cleanup
)
move "%PY_STAGE%" "%PY_DIR%" >nul
if errorlevel 1 (
    if not exist "%PY_DIR%" if exist "%PY_BACKUP%" move "%PY_BACKUP%" "%PY_DIR%" >nul
    goto cleanup
)
set "RC=0"
echo [OK] Embedded Python ready: "%PY_DIR%\python.exe"
goto cleanup

:extraction_failed
echo [ERROR] A complete, working embedded Python package is required. Runtime was not replaced.

:cleanup
if defined DOWNLOADED del /q "%TMP_ZIP%" >nul 2>nul
rem Only delete the marked staging directory directly inside this runtime folder.
for %%I in ("%PY_STAGE%") do if /I "%%~dpI"=="%RUNTIME_DIR%\" if exist "%%~fI\.emailtools-runtime" rmdir /s /q "%%~fI"
rmdir "%RUNTIME_DIR%\.setup-lock" >nul 2>nul
exit /b %RC%

:verify_installed
"%PY_DIR%\python.exe" -I -c "import sys,ssl,ctypes,zipfile; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo [ERROR] The embedded runtime is incomplete. Restore runtime\python from a valid package.
    exit /b 1
)
echo [OK] Embedded Python ready: "%PY_DIR%\python.exe"
exit /b 0
