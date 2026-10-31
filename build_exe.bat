@echo off
title Building lab18b daq Standalone EXE
cd /d "%~dp0"
echo ========================================================
echo   Building lab18b daq Standalone EXE
echo ========================================================
echo.
python build_exe.py
echo.
pause
