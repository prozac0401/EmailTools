@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Compatibility: preserve the original attachment CLI and output format.
call "%~dp0..\run.bat" --legacy-attachments %*
exit /b %ERRORLEVEL%
