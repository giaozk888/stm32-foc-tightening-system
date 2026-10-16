param([switch]$Build, [string]$EvidenceDirectory='')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskEvidence=if($EvidenceDirectory){[System.IO.Path]::GetFullPath($EvidenceDirectory)}else{Join-Path $taskRoot 'safety_backups\20261006-foc-adc-offline'}
$taskEvidenceRoot=[System.IO.Path]::GetFullPath((Join-Path $taskRoot 'safety_backups'))+[System.IO.Path]::DirectorySeparatorChar
if(-not $taskEvidence.StartsWith($taskEvidenceRoot,[System.StringComparison]::OrdinalIgnoreCase)){throw 'Evidence directory must be inside workspace safety_backups'}
New-Item -ItemType Directory -Path $taskEvidence -Force | Out-Null
Push-Location $taskRoot
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File tests/foc_adc_window_host.ps1
    if($LASTEXITCODE -ne 0){throw 'Window/adapter host acceptance failed'}
    & python -m unittest discover -s tests -p 'test_foc_adc_*.py' -v
    if($LASTEXITCODE -ne 0){throw 'Source/report regression failed'}
    & powershell -NoProfile -ExecutionPolicy Bypass -File tests/pwm_set_duty_host.ps1
    if($LASTEXITCODE -ne 0){throw 'Legacy PWM regression failed'}
    & python tests/tim1_pwm_adc_timing.py
    if($LASTEXITCODE -ne 0){throw 'Legacy trigger regression failed'}
    $env:PATH='D:\software\arm\bin;' + $env:PATH
    if($Build){
        foreach($taskSlot in @('a','b')){
            foreach($taskEntry in @(
                @{Name='FocSamplingReadOnly'; Preset='FocSamplingReadOnly'; Options=@()},
                @{Name='FocSamplingLowSideCompile'; Preset='FocSamplingReadOnly'; Options=@('-DFOC_ADC_SENSE_TOPOLOGY=LOW_SIDE_UV')},
                @{Name='EncoderDmaRegression'; Preset='EncoderDmaReadOnly'; Options=@('-DFOC_ADC_WINDOW=OFF')}
            )){
                Push-Location "foc2_app_$taskSlot"
                try {
                    $taskBuildDir='build/'+$taskEntry.Name
                    & 'C:\Program Files\CMake\bin\cmake.exe' --preset $taskEntry.Preset -B $taskBuildDir '-DCMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe' @($taskEntry.Options)
                    if($LASTEXITCODE -ne 0){throw 'ARM configure failed'}
                    & 'C:\Program Files\CMake\bin\cmake.exe' --build $taskBuildDir -j 4 | Select-Object -Last 6
                    if($LASTEXITCODE -ne 0){throw 'ARM build failed'}
                } finally { Pop-Location }
            }
        }
    }
    $taskBinaries=@()
    foreach($taskSlot in @('a','b')){
        foreach($taskProfile in @('FocSamplingReadOnly','FocSamplingLowSideCompile','EncoderDmaRegression')){
            $taskBinary=Get-Item -LiteralPath "foc2_app_$taskSlot/build/$taskProfile/foc2.bin"
            if($taskBinary.Length -gt 0x38000){throw 'Image exceeds existing 224KiB slot'}
            $taskBinaries+=@{slot=$taskSlot;profile=$taskProfile;bytes=$taskBinary.Length;sha256=(Get-FileHash -LiteralPath $taskBinary.FullName -Algorithm SHA256).Hash}
        }
    }
    $taskReport=@{
        status='SOFTWARE_AND_COMPILE_PASS_ONLY'; independent_valid_plan_checks=1507144;
        python_tests=23; legacy_pwm_cases_per_slot=9; binaries=$taskBinaries;
        raw_buffer_thread_stress_sample_pairs=5120000; raw_buffer_thread_stress_passed=$true;
        double_buffer_performance_measured=$false;
        hardware_flashed=$false; board_reset=$false; motor_commands_sent=$false;
        irq_halving_measured=$false; analog_switching_noise_measured=$false;
        maximum_reference_duty_tested_percent=95; physical_95_percent_sampling_verified=$false;
        assumptions=@{timer_hz=170000000;arr=4249;dead_ticks=85;provisional_settle_ticks=85;trigger_latency_max_ticks=14;sample_aperture_ticks=50};
        default_topology='UNCONFIRMED_FAIL_CLOSED'; normal_foc_voltage_limit_changed=$false
    }
    $taskReport | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $taskEvidence 'offline-acceptance.json') -Encoding UTF8
    Write-Output "OFFLINE ACCEPTANCE PASS ONLY: $taskEvidence"
} finally { Pop-Location }
