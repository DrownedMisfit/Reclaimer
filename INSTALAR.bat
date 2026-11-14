@echo off
rem Instala lo que falte para usar Reclaimer (Python, FFmpeg y lo demas). Doble clic; se puede repetir.
cd /d "%~dp0"
if not exist "%~dp0instalar.ps1" (
    echo Falta instalar.ps1. Si abriste esto desde dentro del ZIP, extrae primero el ZIP completo
    echo ^(clic derecho - Extraer todo^) y abre INSTALAR.bat desde la carpeta extraida.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" %*
if errorlevel 1 (
    echo.
    echo La instalacion no termino. Mira instalar.log en esta carpeta.
    pause
    exit /b 1
)
