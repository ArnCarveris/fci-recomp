@echo off
rem Drag your Far Cry Instincts disc image (or the folder with the disc's files) onto this file.
rem The game is checked, recompiled and built on this PC, then installed in "Far Cry Instincts" here.
setlocal
set "DISC=%~1"
if "%DISC%"=="" (
    echo Drag your Far Cry Instincts disc image, or the folder with the disc's files, onto BuildGame.cmd.
    echo Or drag it into this window now and press Enter:
    set /p "DISC="
)
if "%DISC%"=="" exit /b 1
set "DISC=%DISC:"=%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap.ps1" setup "%DISC%"
if errorlevel 1 (
    echo.
    echo The build stopped. The messages above say why; run BuildGame.cmd again to resume.
) else (
    echo.
    echo Finished. Start "Far Cry Instincts\FarCryInstincts.exe".
)
pause
