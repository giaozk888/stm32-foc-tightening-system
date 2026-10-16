param([string]$Workspace = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path)
$ErrorActionPreference = 'Stop'
function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText($Path).Replace("`r`n", "`n")
}
function Without-Rpc([string]$Text) {
    # Evaluate only the newly added RPC-exclusive regions. Nested unrelated
    # directives inside removed blocks must still balance exactly.
    $out = [Collections.Generic.List[string]]::new()
    $depth = 0
    foreach ($line in $Text.Split("`n")) {
        if ($depth -gt 0) {
            if ($line -match '^\s*#\s*(if|ifdef|ifndef)\b') { ++$depth }
            if ($line -match '^\s*#\s*endif\b') { --$depth }
            continue
        }
        if ($line -match '^\s*#if defined\(CAN_RPC_READ_ONLY\)\s*$') { $depth = 1; continue }
        $out.Add($line)
    }
    if ($depth) { throw 'Unbalanced RPC block' }
    return ($out -join "`n")
}
function Compact([string]$Text) { return [regex]::Replace($Text, '\n[ \t]*\n(?:[ \t]*\n)+', "`n`n") }
function Compare-Scoped([string]$Relative, [string]$Current) {
    $old = Read-Normalized (Join-Path $Workspace "refactor_backups/20261004_can_rpc_readonly/$Relative")
    if ((Compact $old) -cne (Compact $Current)) { throw "Changes outside RPC guards: $Relative" }
    Write-Output "PASS RPC OFF preserves prior source: $Relative"
}
foreach ($slot in @('foc2_app_a','foc2_app_b')) {
    $main = Without-Rpc (Read-Normalized (Join-Path $Workspace "$slot/Core/Src/main.c"))
    # The 2026-10-05 live A/B acceptance adds exactly one default-zero
    # test override. It does not change the normal-image health state machine.
    $healthTestOverride = "/* Acceptance-only fault injection; normal images must leave this at zero. */`n#ifndef BOOT_HEALTH_FORCE_FAIL_TEST`n#define BOOT_HEALTH_FORCE_FAIL_TEST        (0U)`n#endif"
    if (-not $main.Contains($healthTestOverride)) { throw 'Missing/default-changed acceptance health override' }
    $main = $main.Replace($healthTestOverride, '#define BOOT_HEALTH_FORCE_FAIL_TEST        (0U)')
    # The prior log-only delay region acquired one nested CAN_LOG_STREAM guard
    # so the delay is shared if RPC-only is selected. Restore that exact region.
    $main = $main.Replace('#if defined(CAN_LOG_STREAM) || defined(CAN_RPC_READ_ONLY)', '#if defined(CAN_LOG_STREAM)')
    $main = $main.Replace("#if defined(CAN_LOG_STREAM)`n        PW_CanLog_Service(HAL_GetTick());`n#endif`n#endif",
        "        PW_CanLog_Service(HAL_GetTick());`n#endif")
    Compare-Scoped "$slot/Core/Src/main.c" $main
    Compare-Scoped "$slot/Middleware/pigweed/pw_rpc_service.cc" (Without-Rpc (Read-Normalized (Join-Path $Workspace "$slot/Middleware/pigweed/pw_rpc_service.cc")))
    $presets = (Read-Normalized (Join-Path $Workspace "$slot/CMakePresets.json")) | ConvertFrom-Json
    $rpc = $presets.configurePresets | Where-Object name -eq 'CanRpcReadOnly'
    if ($rpc.cacheVariables.CAN_CONTROL_REJECT_ONLY -ne 'ON' -or $rpc.cacheVariables.CAN_RPC_READ_ONLY -ne 'ON' -or
        $rpc.cacheVariables.SAFETY_LOCKED_BOOT -ne 'OFF') { throw 'RPC preset scope mismatch' }
    foreach ($profile in @('UartZeroCopy','UartZeroCopy2M','UartZeroCopySafety')) {
        $cache = Read-Normalized (Join-Path $Workspace "$slot/build/$profile/CMakeCache.txt")
        if ($cache -notmatch '(?m)^CAN_RPC_READ_ONLY:BOOL=OFF$') { throw "Existing profile enables RPC: $slot/$profile" }
    }
}
$can = Without-Rpc (Read-Normalized (Join-Path $Workspace 'firmware_common/can_status_tx.c'))
$can = $can.Replace('#if defined(CAN_SHADOW_DIAG) || defined(CAN_RPC_READ_ONLY)', '#if defined(CAN_SHADOW_DIAG)')
Compare-Scoped 'firmware_common/can_status_tx.c' $can
foreach ($relative in @('Middleware/pigweed/pw_rpc_service.cc','Middleware/pigweed/pw_rpc_service.h',
    'Middleware/pigweed/pw_log_backend.h','CMakePresets.json')) {
    if ((Read-Normalized (Join-Path $Workspace "foc2_app_a/$relative")) -cne
        (Read-Normalized (Join-Path $Workspace "foc2_app_b/$relative"))) { throw "A/B drift: $relative" }
}
Write-Output 'PASS A/B shared interfaces identical; prior motion/FOC/safety/Flash handlers unchanged; no board actions.'
