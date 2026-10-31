@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
set "LabOSInstallExit=%ERRORLEVEL%"
echo.
echo Install exit code: %LabOSInstallExit%. Details: install.log
pause
exit /b %LabOSInstallExit%
