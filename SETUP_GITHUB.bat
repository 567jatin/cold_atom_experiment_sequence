@echo off
setlocal
echo =======================================================================
echo          lab18b daq - GitHub Repository Setup Helper
echo =======================================================================
echo.
echo Checking for Git...
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git command was not found in your system PATH.
    echo Please install Git for Windows from https://git-scm.com/download/win
    echo or use GitHub Desktop (https://desktop.github.com) to open this folder.
    echo.
    pause
    exit /b 1
)

echo Initializing local Git repository...
git init
git add .
git commit -m "Initial commit: lab18b daq - FPGA TTL & Analog Sequence Controller"
git branch -M main

echo.
echo =======================================================================
echo Local Git repository initialized with all project files!
echo.
echo To push this folder to your GitHub account:
echo   1. Create an empty new repository on https://github.com/new (e.g. 'lab18b_daq')
echo   2. Run the following two commands (replace URL with your repository URL):
echo.
echo      git remote add origin https://github.com/<YOUR-USERNAME>/lab18b_daq.git
echo      git push -u origin main
echo.
echo =======================================================================
pause
