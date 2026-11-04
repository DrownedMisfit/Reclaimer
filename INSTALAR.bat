@echo off
rem Crea el entorno de Python e instala lo necesario. Solo hace falta la primera vez.
cd /d "%~dp0"
where python >nul 2>nul || (echo Falta Python. Instalalo con: winget install Python.Python.3.12 & pause & exit /b 1)
where ffmpeg >nul 2>nul || (echo Falta FFmpeg. Instalalo con: winget install Gyan.FFmpeg & pause & exit /b 1)
if not exist ".venv" python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Listo. Ya puedes abrir el programa con INICIAR.bat
pause
