$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$excluded = @(
    '__attribute__', 'main', 'TightenParams_Validate', 'TightenParams_RestoreDefaults',
    'TightenParams_LoadLegacyFlash', 'TightenParams_LoadFromFlash',
    'TightenParams_SaveToFlash', 'TightenParams_SendValue',
    'TightenParams_PrintAll', 'TightenParams_GetOne', 'TightenParams_SetOne',
    'Current_FromRaw_mA', 'ADC_GetInjectedSnapshot'
)

function Get-Functions([string]$source) {
    $result = @{}
    # Top-level function closing braces are column zero in these Cube sources.
    $pattern = '(?ms)^(?:static[ \t]+)?(?:[A-Za-z_]\w*[ \t*]+)+([A-Za-z_]\w*)\([^;]*?\)\n\{.*?^\}'
    foreach ($match in [regex]::Matches($source, $pattern)) {
        $result[$match.Groups[1].Value] = $match.Value
    }
    return $result
}

function Normalize-Params([string]$source) {
    $source = $source.Replace('tighten_params = tighten_params_defaults;',
        'TightenParams_ResetDefaults(&recipe_state.params);')
    $mapping = @{
        tighten_params = 'recipe_state.params'
        tighten_params_flash_valid = 'recipe_state.flash_valid'
        tighten_params_dirty = 'recipe_state.dirty'
        tighten_params_last_crc32 = 'recipe_state.last_crc32'
        tighten_params_kvs_ready = 'recipe_state.kvs_ready'
        tighten_params_kvs_migrated = 'recipe_state.kvs_migrated'
    }
    foreach ($name in $mapping.Keys) {
        $source = [regex]::Replace($source, '\b' + $name + '\b', $mapping[$name])
    }
    return $source
}

foreach ($slot in @('a', 'b')) {
    $before = (Get-Content -Raw -LiteralPath (Join-Path $taskRoot "refactor_backups/20261002_cpp_params/main_$slot.c")).Replace("`r`n", "`n")
    $after = (Get-Content -Raw -LiteralPath (Join-Path $taskRoot "foc2_app_$slot/Core/Src/main.c")).Replace("`r`n", "`n")
    $oldFunctions = Get-Functions $before
    $newFunctions = Get-Functions $after
    foreach ($critical in @('FOC_CurrentLoopStep', 'FOC_EncoderSpeedUpdate',
        'HAL_ADCEx_InjectedConvCpltCallback', 'HAL_ADC_ErrorCallback',
        'MotorControlTask', 'TighteningTask', 'Protocol_HandleLine',
        'StartupTask', 'PowerStage_Enable', 'PowerStage_Disable')) {
        if (!$oldFunctions.ContainsKey($critical) -or !$newFunctions.ContainsKey($critical)) {
            throw "Critical function not captured: $slot/$critical"
        }
    }
    $checked = 0
    foreach ($name in $oldFunctions.Keys) {
        if ($excluded -contains $name) { continue }
        if (!$newFunctions.ContainsKey($name)) { throw "Missing function $slot/$name" }
        if ((Normalize-Params $oldFunctions[$name]) -cne $newFunctions[$name]) {
            throw "Unexpected non-parameter function change $slot/$name"
        }
        $checked++
    }
    if ($checked -lt 80) { throw "Unexpectedly few function comparisons: $checked" }
    Write-Output "PASS: slot $slot, $checked preserved functions (only explicit recipe-state renames and boot-default adapter normalized)."
}
