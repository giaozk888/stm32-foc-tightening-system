@echo off
setlocal
cd /d "%~dp0.."
set "TASK_IDF_PYTHON=C:\Espressif\tools\python\v6.1\venv\Scripts\python.exe"
if not exist "%TASK_IDF_PYTHON%" (
    echo ESP-IDF Python not found. No configuration created; nothing flashed.
    pause
    exit /b 1
)
"%TASK_IDF_PYTHON%" "%~dp0provision_gateway.py" --interactive
if errorlevel 1 (
    echo Configuration failed. No board has been flashed or reset.
) else (
    echo Private NVS image created. Contains secrets; do not share it.
    echo No board has been flashed or reset.
)
pause
