@echo off
chcp 65001 > nul
title Compilador - Portal de Seguros

echo.
echo ============================================================
echo       COMPILADOR - PORTAL DE SEGUROS
echo       Generador de Ejecutable para Servidor LAN
echo ============================================================
echo.

:: Verificar que Python este instalado
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en el PATH
    echo         Instale Python desde https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Verificar si estamos en un entorno virtual
if defined VIRTUAL_ENV (
    echo [OK] Entorno virtual detectado: %VIRTUAL_ENV%
) else (
    echo [!] No se detecto entorno virtual activo
    echo     Se recomienda usar un entorno virtual
)

echo.
echo [1/4] Instalando dependencias...
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Error al instalar dependencias
    pause
    exit /b 1
)

echo.
echo [2/4] Verificando PyInstaller...
echo.
pip show pyinstaller > nul 2>&1
if errorlevel 1 (
    echo [!] Instalando PyInstaller...
    pip install pyinstaller
)

echo.
echo [3/4] Limpiando compilaciones anteriores...
echo.
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo.
echo [4/4] Compilando ejecutable...
echo      Esto puede tardar varios minutos...
echo.
pyinstaller portal_seguros.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] La compilacion fallo
    echo         Revise los errores anteriores
    pause
    exit /b 1
)

echo.
echo [5/5] Copiando archivos adicionales...
echo.

:: Crear estructura de carpetas
if not exist "dist\PortalSeguros_Servidor\app\templates" mkdir "dist\PortalSeguros_Servidor\app\templates"
if not exist "dist\PortalSeguros_Servidor\app\static" mkdir "dist\PortalSeguros_Servidor\app\static"
if not exist "dist\PortalSeguros_Servidor\archivos_usuarios" mkdir "dist\PortalSeguros_Servidor\archivos_usuarios"
if not exist "dist\PortalSeguros_Servidor\uploads" mkdir "dist\PortalSeguros_Servidor\uploads"
if not exist "dist\PortalSeguros_Servidor\downloads" mkdir "dist\PortalSeguros_Servidor\downloads"

:: Copiar templates y static
xcopy /E /I /Y "app\templates" "dist\PortalSeguros_Servidor\app\templates" > nul
xcopy /E /I /Y "app\static" "dist\PortalSeguros_Servidor\app\static" > nul

:: Copiar base de datos si existe
if exist "portal_seguros.db" (
    copy /Y "portal_seguros.db" "dist\PortalSeguros_Servidor\" > nul
    echo [OK] Base de datos copiada
)

echo.
echo ============================================================
echo       COMPILACION EXITOSA
echo ============================================================
echo.
echo El ejecutable se encuentra en:
echo   dist\PortalSeguros_Servidor\
echo.
echo Para distribuir el servidor, copie toda la carpeta
echo "PortalSeguros_Servidor" a la PC destino.
echo.
echo Archivo principal: PortalSeguros_Servidor.exe
echo.
echo ============================================================
echo.

:: Preguntar si quiere abrir la carpeta
set /p abrir="Desea abrir la carpeta del ejecutable? (S/N): "
if /i "%abrir%"=="S" (
    explorer dist\PortalSeguros_Servidor
)

pause
