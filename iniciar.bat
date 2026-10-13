@echo off
chcp 65001 >nul
title Gestion de Ingresos y Gastos
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  No se encontro Python. Instalalo desde https://www.python.org/downloads/
    echo  IMPORTANTE: marca la casilla "Add python.exe to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo  Preparando el sistema por primera vez. Esto tarda menos de un minuto...
    python -m venv .venv
    if errorlevel 1 goto error
)

".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto error

".venv\Scripts\python.exe" app.py
pause
exit /b 0

:error
echo.
echo  Ocurrio un error al preparar el sistema. Revisa tu conexion a Internet e intentalo de nuevo.
pause
exit /b 1
