@echo off
setlocal EnableExtensions DisableDelayedExpansion
call "%~dp0setup_runtime.bat"
if errorlevel 1 exit /b 1
"%~dp0runtime\python\python.exe" -X utf8 "%~dp0tools\setup_desktop.py"
exit /b %ERRORLEVEL%
