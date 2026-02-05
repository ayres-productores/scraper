@echo off
chcp 65001 > nul
title Portal de Seguros - Servidor LAN

echo.
echo Iniciando Portal de Seguros en modo LAN...
echo.

python servidor_lan.py

pause
