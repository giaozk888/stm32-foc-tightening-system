@echo off
setlocal
cd /d "%~dp0.."
set "TASK_IDF_PYTHON=C:\Espressif\tools\python\v6.1\venv\Scripts\python.exe"
set "TASK_PRIVATE_DIR=%CD%\esp32_s3_gateway\local_config\private_hotspot"
set "TASK_NVS_OUTPUT=%TASK_PRIVATE_DIR%\network_hotspot_nvs_%RANDOM%_%RANDOM%.bin"
if not exist "%TASK_IDF_PYTHON%" (
    echo ESP-IDF Python not found. Nothing flashed.
    pause
    exit /b 1
)
if not exist "%TASK_PRIVATE_DIR%" mkdir "%TASK_PRIVATE_DIR%"
if errorlevel 1 exit /b 1
icacls "%TASK_PRIVATE_DIR%" /inheritance:r /grant:r "%USERDOMAIN%\%USERNAME%:(OI)(CI)F" "SYSTEM:(OI)(CI)F" >nul
if errorlevel 1 (
    echo Cannot protect the private output directory. No secrets requested.
    pause
    exit /b 1
)
echo Offline configuration only. No board will be flashed or reset.
echo SSID: LubanCat-ESP32
echo Upload: http://192.168.50.1:18089/api/v1/observations
echo Confirm the LubanCat-to-cloud SSH tunnel health first.
echo This is a trusted-LAN HTTP demo plus SSH, NOT end-to-end HTTPS.
echo Hotspot password is captured over SSH without displaying it.
echo Enter only the existing SERVER API TOKEN locally.
echo The cloud SSH root password is NOT the server API token.
echo Do not share the output image or screenshots of secrets.
"%TASK_IDF_PYTHON%" "%~dp0provision_gateway.py" --interactive --lubancat-hotspot --ssid "LubanCat-ESP32" --url "http://192.168.50.1:18089/api/v1/observations" --output "%TASK_NVS_OUTPUT%"
if errorlevel 1 (
    echo Configuration failed. Nothing flashed or reset.
) else (
    echo Private configuration ready. Contains secrets; do not share it.
    echo Tell Codex that configuration was generated. Nothing flashed or reset.
)
pause
