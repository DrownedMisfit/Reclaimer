@echo off
chcp 65001 >nul
title Reclaimer - Motor de IA
cd /d "%~dp0"
echo Instalando (o reparando) el motor de IA de Reclaimer en esta carpeta...
echo (PyTorch para tu tarjeta, SAM 2.1 y Demucs. Puede tardar un rato la primera vez.)
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.12 "%~dp0instalar_motor.py" %*
) else (
    python "%~dp0instalar_motor.py" %*
)
