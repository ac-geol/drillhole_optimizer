@echo off
rem Double-click to start the Infill Drilling Budget Optimiser.
rem Requires uv: https://docs.astral.sh/uv/getting-started/installation/
setlocal
title Infill Drilling Budget Optimiser

rem Run from the folder this file lives in, wherever it was launched from.
cd /d "%~dp0"

rem Find uv: on PATH, or in its default install folder if the PATH
rem has not refreshed since installing.
set "UV=uv"
where uv >nul 2>nul
if errorlevel 1 (
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "UV=%USERPROFILE%\.local\bin\uv.exe"
    ) else (
        echo uv was not found.
        echo.
        echo Install it by running this in PowerShell, then try again:
        echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        echo.
        pause
        exit /b 1
    )
)

echo Starting the app. The first run installs Python and packages
echo and can take a few minutes. Your browser will open when ready.
echo.
echo Keep this window open while you work. Close it to stop the app.
echo.

"%UV%" run streamlit run app.py
if errorlevel 1 (
    echo.
    echo The app stopped with an error. See the messages above.
    pause
    exit /b 1
)
endlocal
