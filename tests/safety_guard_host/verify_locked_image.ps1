param(
    [string]$ArmBin = 'D:\software\arm\bin'
)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$nm = Join-Path $ArmBin 'arm-none-eabi-nm.exe'
$objdump = Join-Path $ArmBin 'arm-none-eabi-objdump.exe'
$forbidden = @(
    'PWM_StartAll', 'PowerStage_Enable', 'ADC_RunZeroCalibrate',
    'HAL_TIM_PWM_Start', 'HAL_TIMEx_PWMN_Start', 'HAL_ADCEx_InjectedStart_IT',
    'MotorControlTask', 'TighteningTask', 'ProtocolTask', 'RouterTask', 'BootHealthTask',
    'BootMeta_WriteV3', 'BootMeta_WriteV2', 'PW_Rpc_ProtocolSend', 'PW_TransferFlash_Write',
    'HAL_FLASH_Program', 'HAL_FLASHEx_Erase', 'HAL_FLASH_Unlock'
)
foreach ($slot in @('a', 'b')) {
    $build = Join-Path $taskRoot "foc2_app_$slot/build/SafetyLocked"
    $elf = Join-Path $build 'foc2.elf'
    $cache = Get-Content -LiteralPath (Join-Path $build 'CMakeCache.txt')
    foreach ($setting in @('SAFETY_LOCKED_BOOT:BOOL=ON', 'CAN_STATUS_TELEMETRY:BOOL=ON',
                          'CAN_CONTROL_REJECT_ONLY:BOOL=ON', 'CAN_LOG_STREAM:BOOL=OFF',
                          'CAN_LINK_PROBE_ONLY:BOOL=OFF', 'CAN_SHADOW_DIAG:BOOL=OFF')) {
        if ($cache -notcontains $setting) { throw "Unsafe/missing build setting: $setting" }
    }
    $symbols = & $nm --defined-only $elf
    if ($LASTEXITCODE -ne 0) { throw "nm failed for $elf" }
    foreach ($name in $forbidden) {
        if ($symbols -match ('\s' + [regex]::Escape($name) + '$')) {
            throw "Forbidden symbol linked in locked profile: $name ($slot)"
        }
    }
    foreach ($name in @('SafetyLockedBoot_RunForever', 'SafetySample_Reasons',
                       'CAN_StatusTx_TrySafetyFrame', 'SafetyGuard_EncodeLocked')) {
        if (!($symbols -match ('\s' + [regex]::Escape($name) + '$'))) {
            throw "Missing locked-profile implementation: $name ($slot)"
        }
    }
    $sections = & $objdump -h $elf
    if ($LASTEXITCODE -ne 0) { throw "objdump failed for $elf" }
    $base = if ($slot -eq 'a') { 0x08008000 } else { 0x08040000 }
    $baseHex = '{0:x8}' -f $base
    if (!($sections -match ("\.isr_vector\s+[0-9a-f]+\s+$baseHex\s+$baseHex"))) {
        throw "Wrong vector address for $slot"
    }
    $bytes = [System.IO.File]::ReadAllBytes((Join-Path $build 'foc2.bin'))
    if ($bytes.Length -lt 8 -or $bytes.Length -gt 229376) { throw "Invalid image size ($slot)" }
    $stack = [BitConverter]::ToUInt32($bytes, 0)
    $reset = [BitConverter]::ToUInt32($bytes, 4)
    if ($stack -lt 0x20000000 -or $stack -gt 0x20020000 -or ($stack % 8) -ne 0 -or
        ($reset -band 1) -ne 1 -or $reset -lt $base -or $reset -ge ($base + 229376)) {
        throw "Invalid initial SP/reset vector ($slot)"
    }
    $hash = (Get-FileHash -LiteralPath (Join-Path $build 'foc2.bin') -Algorithm SHA256).Hash
    Write-Output "Locked $slot PASS: vector=$baseHex bytes=$($bytes.Length) SHA256=$hash"
}
Write-Output 'Static image audit only. Does NOT verify wiring, output levels or hardware safety.'
