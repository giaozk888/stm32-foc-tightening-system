param([string]$Compiler='D:\Qt\Tools\mingw1310_64\bin\gcc.exe')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskOut=Join-Path $PSScriptRoot 'foc_adc_window_build'
New-Item -ItemType Directory -Path $taskOut -Force | Out-Null
$taskCommon=Join-Path $taskRoot 'firmware_common'
$taskFlags=@('-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG','-I',$taskCommon)
$taskExe=Join-Path $taskOut 'planner.exe'
& $Compiler @taskFlags (Join-Path $taskCommon 'foc_adc_window.c') (Join-Path $PSScriptRoot 'foc_adc_window_host.c') -o $taskExe
if($LASTEXITCODE -ne 0){throw 'Planner host build failed'}
& $taskExe
if($LASTEXITCODE -ne 0){throw 'Planner tests failed'}
$taskExe=Join-Path $taskOut 'raw_buffer.exe'
& $Compiler @taskFlags (Join-Path $taskCommon 'foc_adc_raw_buffer.c') (Join-Path $PSScriptRoot 'foc_adc_raw_buffer_host.c') -o $taskExe
if($LASTEXITCODE -ne 0){throw 'Raw double-buffer host build failed'}
& $taskExe
if($LASTEXITCODE -ne 0){throw 'Raw double-buffer tests failed'}
$taskExe=Join-Path $taskOut 'statistics_task.exe'
& $Compiler @taskFlags -I (Join-Path $PSScriptRoot 'foc_adc_mock') (Join-Path $taskCommon 'foc_adc_statistics_task.c') (Join-Path $PSScriptRoot 'foc_adc_statistics_task_host.c') -o $taskExe
if($LASTEXITCODE -ne 0){throw 'Statistics worker host build failed'}
& $taskExe
if($LASTEXITCODE -ne 0){throw 'Statistics worker tests failed'}
foreach($taskSense in @(0,2,3)){
    $taskActualSense=$taskSense
    $taskRcFlags=@()
    if($taskSense -eq 3){
        $taskActualSense=2
        $taskRcFlags=@('-DFOC_ADC_RC_DIAGNOSTIC=1','-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1','-DFOC_PROTECTED_CLOSED_LOOP=1')
    }
    $taskExe=Join-Path $taskOut "adapter_$taskSense.exe"
    & $Compiler @taskFlags @taskRcFlags -I (Join-Path $PSScriptRoot 'foc_adc_mock') "-DFOC_ADC_SENSE_TOPOLOGY=$taskActualSense" (Join-Path $taskCommon 'foc_adc_window.c') (Join-Path $taskCommon 'foc_adc_raw_buffer.c') (Join-Path $taskCommon 'foc_adc_timing_stm32.c') (Join-Path $PSScriptRoot 'foc_adc_adapter_host.c') -o $taskExe
    if($LASTEXITCODE -ne 0){throw 'Adapter host build failed'}
    & $taskExe
    if($LASTEXITCODE -ne 0){throw 'Adapter tests failed'}
}
Write-Output 'HOST PASS ONLY: no probe/serial/flash/reset/physical analog evidence.'
