@echo off
rem Doble clic en este archivo para abrir Reclaimer.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo No se encuentra el entorno de Python ^(.venv^).
    echo Ejecuta INSTALAR.bat primero.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
