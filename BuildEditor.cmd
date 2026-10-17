@echo off
rem Build the map editor for the game BuildGame.cmd set up. The game's Map Editor menu then starts it.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap.ps1" editor
if errorlevel 1 (
    echo.
    echo The build stopped. The messages above say why; run BuildEditor.cmd again to resume.
) else (
    echo.
    echo Finished. Choose Map Editor in the game's main menu.
)
pause
