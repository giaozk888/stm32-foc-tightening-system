param([switch]$Esp32, [switch]$Rpc, [switch]$Transfer, [switch]$CanFd)
$ErrorActionPreference = 'Stop'
$taskWorkspace = Split-Path $PSScriptRoot -Parent
$taskCmake = 'C:\Program Files\CMake\bin\cmake.exe'
$env:PATH = 'D:\software\arm\bin;D:\software\ninja;' + $env:PATH
$taskPreset = if ($Rpc) { 'RouterRpcReadOnly' } else { 'RouterNetworkReadOnly' }
$taskEspBuild = if ($Rpc) { 'build_router_rpc' } else { 'build_router' }
$taskDefaults = if ($Rpc) { 'sdkconfig.defaults;sdkconfig.router_rpc.defaults' } else { 'sdkconfig.defaults;sdkconfig.router.defaults' }
if ($CanFd -and $Esp32) {
    throw 'CAN FD selects the STM32/LubanCat link, not the ESP32 UART/TCP link. Build ESP32 separately without -CanFd.'
}
if ($Transfer) {
    $taskPreset = 'RouterTransferReadOnly'
    $taskEspBuild = 'build_router_transfer'
    $taskDefaults = 'sdkconfig.defaults;sdkconfig.router_transfer.defaults'
}
if ($CanFd) {
    $taskPreset = 'CanFdReadOnly'
    Write-Output 'CAN FD read-only profile: 500k, BRS OFF, status/log/RPC enabled; power stage hard-locked.'
}
if ($Esp32) {
    . 'C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1'
    $env:PYTHONUTF8 = '1'
    $env:IDF_CCACHE_ENABLE = '0'
    Push-Location (Join-Path $taskWorkspace 'esp32_s3_gateway')
    try {
        $taskConfig = (Join-Path (Get-Location).Path "$taskEspBuild/sdkconfig").Replace('\','/')
        idf.py -B $taskEspBuild -D "SDKCONFIG=$taskConfig" -D "SDKCONFIG_DEFAULTS=$taskDefaults" -D 'CMAKE_PROGRAM_PATH=C:/Espressif/tools/xtensa-esp-elf/esp-15.2.0_20251204/xtensa-esp-elf/bin' build
        if ($LASTEXITCODE -ne 0) { throw 'ESP32 Router build failed' }
    } finally { Pop-Location }
} else {
    foreach ($taskSlot in @('a','b')) {
        Push-Location (Join-Path $taskWorkspace "foc2_app_$taskSlot")
        try {
            & $taskCmake --preset $taskPreset -D 'CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
            if ($LASTEXITCODE -ne 0) { throw 'Router configure failed' }
            & $taskCmake --build --preset $taskPreset -j 4
            if ($LASTEXITCODE -ne 0) { throw 'Router build failed' }
        } finally { Pop-Location }
    }
}
Write-Output 'BUILD ONLY: no serial port opened, no Flash/reset/motion action.'
