@echo off
title Stilwater installer
rem Installs Stilwater into Saints Row 2. Pass -Game "<folder>" if the game isn't found by itself.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
