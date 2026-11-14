@echo off
rem Doble clic en este archivo para abrir Reclaimer.
cd /d "%~dp0"
if exist ".venv\instalado.ok" goto abrir
rem (instalaciones de antes del instalador nuevo: si todo carga, se marca como instalado)
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -c "import PySide6, cv2, faster_whisper" >nul 2>nul && (
    type nul > ".venv\instalado.ok"
    goto abrir
)
echo Reclaimer aun no esta instalado del todo en este PC. Voy a instalar lo que falta...
call "%~dp0INSTALAR.bat"
exit /b
:abrir
start "" ".venv\Scripts\pythonw.exe" main.py %*
