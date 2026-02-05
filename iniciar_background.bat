@echo off
chcp 65001 > nul

echo.
echo Iniciando Portal de Seguros en background...
echo.

:: Crear carpeta de logs si no existe
if not exist "logs" mkdir logs

:: Ejecutar el script VBS que inicia en background
cscript //nologo iniciar_background.vbs

echo.
echo Para ver los logs: type logs\servidor.log
echo Para detener:      taskkill /f /im python.exe
echo.
