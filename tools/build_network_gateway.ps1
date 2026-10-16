param(
    [string]$IdfProfile = 'C:\Espressif\tools\Microsoft.v6.1.PowerShell_profile.ps1',
    [string]$ToolBin = 'C:\Espressif\tools\xtensa-esp-elf\esp-15.2.0_20251204\xtensa-esp-elf\bin'
)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path $PSScriptRoot -Parent
$taskEsp = Join-Path $taskProject 'esp32_s3_gateway'
if (-not (Test-Path -LiteralPath $IdfProfile)) { throw 'ESP-IDF profile missing' }
. $IdfProfile
$env:PYTHONUTF8 = '1'
$env:IDF_CCACHE_ENABLE = '0'
Push-Location $taskEsp
try {
    $taskConfig = (Join-Path $taskEsp 'build_network\sdkconfig').Replace('\','/')
    $taskToolBin = $ToolBin.Replace('\','/')
    idf.py -B build_network -D "SDKCONFIG=$taskConfig" -D "CMAKE_PROGRAM_PATH=$taskToolBin" build
    if ($LASTEXITCODE -ne 0) { throw 'Gateway build failed; nothing flashed' }
} finally { Pop-Location }
