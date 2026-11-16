@echo off
chcp 65001 >nul
title Reclaimer - Motor de IA
cd /d "%~dp0"
echo Instalando (o reparando) el motor de IA de Reclaimer en esta carpeta...
echo (PyTorch para tu tarjeta, SAM 2.1 y Demucs. Puede tardar un rato la primera vez.)
echo.
if exist "%~dp0..\..\python\python.exe" if exist "%~dp0..\..\Reclaimer.exe" (
    rem Version todo en uno: su propio Python, y lo pesado en motor_ia_datos (junto a Reclaimer.exe)
    if not defined RECLAIMER_MOTOR_DATOS for %%I in ("%~dp0..\..") do set "RECLAIMER_MOTOR_DATOS=%%~fI\motor_ia_datos"
    "%~dp0..\..\python\python.exe" -E -s "%~dp0instalar_motor.py" %*
    goto :fin
)
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.12 "%~dp0instalar_motor.py" %*
) else (
    python "%~dp0instalar_motor.py" %*
)
:fin
