@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
if errorlevel 1 goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Program-Connector.ps1"
set "LabOSProgramExit=%ERRORLEVEL%"
goto done
:failed
set "LabOSProgramExit=%ERRORLEVEL%"
:done
echo.
echo Program connector setup exit code: %LabOSProgramExit%
pause
exit /b %LabOSProgramExit%
