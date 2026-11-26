@echo off
setlocal
title Anki Scribe
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

where uv >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Anki Scribe needs its Python environment, and "uv" was not found.
    echo   Install uv from https://docs.astral.sh/uv/ then run this file again.
    echo.
    pause
    exit /b 1
)

echo.
echo   First run - downloading dependencies. This takes a minute or two...
echo.
uv sync
if errorlevel 1 (
    echo.
    echo   Setup failed. Check the error above.
    echo.
    pause
    exit /b 1
)

:run
".venv\Scripts\python.exe" run.py
if errorlevel 1 (
    echo.
    echo   Anki Scribe stopped with an error.
    echo.
    pause
)
