@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title EmailTools
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "PYTHON_EXE=%~dp0runtime\python\python.exe"
if not exist "%PYTHON_EXE%" (
    call "%~dp0setup_runtime.bat"
    if errorlevel 1 goto setup_failed
)
echo [Runtime] "%PYTHON_EXE%"
"%PYTHON_EXE%" -X utf8 "%~dp0main.py" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [ERROR] Exit code: %RC%
    if not defined EMAILTOOLS_NO_PAUSE pause
)
popd
exit /b %RC%

:setup_failed
echo [ERROR] Embedded Python setup failed.
if not defined EMAILTOOLS_NO_PAUSE pause
popd
exit /b 1
