@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Compatibility: the default opens the unified UI; --cli keeps old output.
if /I "%~1"=="--cli" (
    if "%~2"=="" (
        call "%~dp0..\run.bat" --legacy-tables
    ) else (
        call "%~dp0..\run.bat" --legacy-tables "%~2"
    )
) else (
    call "%~dp0..\run.bat" %*
)
exit /b %ERRORLEVEL%
