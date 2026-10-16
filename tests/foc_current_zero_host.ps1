param([string]$Compiler='D:\Qt\Tools\mingw1310_64\bin\gcc.exe')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskOut=Join-Path $PSScriptRoot 'foc_current_zero_build'
New-Item -ItemType Directory -Path $taskOut -Force | Out-Null
$taskCommon=Join-Path $taskRoot 'firmware_common'
$taskExe=Join-Path $taskOut 'stable_zero.exe'
& $Compiler -std=c11 -O2 -Wall -Wextra -Werror -pedantic -UNDEBUG -I $taskCommon `
    (Join-Path $taskCommon 'foc_current_zero.c') (Join-Path $PSScriptRoot 'foc_current_zero_host.c') -o $taskExe
if($LASTEXITCODE -ne 0){throw 'Stable-zero native host build failed'}
& $taskExe
if($LASTEXITCODE -ne 0){throw 'Stable-zero host tests failed'}
$taskExe=Join-Path $taskOut 'stable_zero_port.exe'
& $Compiler -std=c11 -O2 -Wall -Wextra -Werror -pedantic -UNDEBUG -I $taskCommon `
    (Join-Path $taskCommon 'foc_current_zero.c') (Join-Path $PSScriptRoot 'foc_current_zero_port_host.c') -o $taskExe
if($LASTEXITCODE -ne 0){throw 'Stable-zero binding host build failed'}
& $taskExe
if($LASTEXITCODE -ne 0){throw 'Stable-zero binding host tests failed'}
Write-Output 'OFFLINE ONLY: no serial, probe, Flash, reset or motor action.'
