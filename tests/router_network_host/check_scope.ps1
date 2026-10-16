$ErrorActionPreference = 'Stop'
$taskWorkspace = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$taskGcc = 'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
$taskMock = Join-Path $taskWorkspace 'tests/uart_zero_copy_host/mocks'
foreach ($taskSlot in @('a','b')) {
    $taskInclude = Join-Path $taskWorkspace "foc2_app_$taskSlot/Core/Inc"
    foreach ($taskSource in @('router.c','esp_link.c')) {
        $taskOld = Join-Path $taskWorkspace "refactor_backups/20261005_router_network/foc2_app_$taskSlot/Core/Src/$taskSource"
        $taskNew = Join-Path $taskWorkspace "foc2_app_$taskSlot/Core/Src/$taskSource"
        $taskBefore = (& $taskGcc -E -P -I $taskMock -I $taskInclude $taskOld) -join "`n"
        if ($LASTEXITCODE -ne 0) { throw 'Baseline preprocessing failed' }
        $taskAfter = (& $taskGcc -E -P -I $taskMock -I $taskInclude $taskNew) -join "`n"
        if ($LASTEXITCODE -ne 0) { throw 'Current preprocessing failed' }
        # Preprocessor whitespace is not a semantic change.
        $taskBefore = [regex]::Replace($taskBefore, '\s+', ' ')
        $taskAfter = [regex]::Replace($taskAfter, '\s+', ' ')
        if ($taskBefore -cne $taskAfter) { throw "Feature-OFF code changed: $taskSlot/$taskSource" }
        Write-Output "PASS feature OFF retains prior preprocessed source: $taskSlot/$taskSource"
    }
}
foreach ($taskRelative in @('Core/Src/router.c','Core/Inc/router.h','Core/Src/esp_link.c')) {
    $taskA = [IO.File]::ReadAllText((Join-Path $taskWorkspace "foc2_app_a/$taskRelative"))
    $taskB = [IO.File]::ReadAllText((Join-Path $taskWorkspace "foc2_app_b/$taskRelative"))
    if ($taskA.Replace("`r`n","`n") -cne $taskB.Replace("`r`n","`n")) { throw "A/B drift: $taskRelative" }
}
Write-Output 'PASS A/B communication source synchronized; no board action.'
foreach ($taskSlot in @('a','b')) {
    $taskTransferBaseline = Join-Path $taskWorkspace "refactor_backups/20261006_router_transfer_before/foc2_app_$taskSlot/Core/Src/main.c"
    if (Test-Path -LiteralPath $taskTransferBaseline) {
        # This baseline includes the already audited encoder/ADC double-buffer work.
        # Do not compare those prior changes with the older pre-ADC snapshot.
        $taskExpected = [IO.File]::ReadAllText($taskTransferBaseline).Replace("`r`n","`n")
        $taskCurrent = [IO.File]::ReadAllText((Join-Path $taskWorkspace "foc2_app_$taskSlot/Core/Src/main.c")).Replace("`r`n","`n")
        if ($taskCurrent.Contains('#if defined(FOC_ISOLATED_CONCURRENCY)')) {
            # Independently verify exact OFF equality to the new snapshot first.
            python tools/check_isolated_scope.py
            if ($LASTEXITCODE -ne 0) { throw 'Isolated scope audit failed' }
            $taskCurrent = [IO.File]::ReadAllText((Join-Path $taskWorkspace "refactor_backups/20261006_isolated_concurrency_before/foc2_app_$taskSlot/Core/Src/main.c")).Replace("`r`n","`n")
        }
        $taskTransferGuard = '(?ms)^#if defined\(ROUTER_READ_ONLY_TRANSFER\)\n(?<body>.*?)^#endif\n'
        if ([regex]::Matches($taskCurrent,$taskTransferGuard).Count -ne 3) { throw 'Expected three dedicated Transfer guards' }
        $taskCurrent = [regex]::Replace($taskCurrent,$taskTransferGuard,{
            param($taskMatch)
            if ($taskMatch.Groups['body'].Value -match '(?m)^#(if|else|elif|endif)') { throw 'Unexpected nested Transfer guard' }
            return ''
        })
        if ($taskExpected -cne $taskCurrent) { throw "Unrelated current main.c change: slot $taskSlot" }
        Write-Output "PASS slot $taskSlot current baseline: only three opt-in Transfer integration blocks."
        continue
    }
    $taskBaselineMain = Join-Path $taskWorkspace "safety_backups/20261005-router-live-acceptance/main-$taskSlot-before-stack-fix.c"
    if (Test-Path -LiteralPath $taskBaselineMain) {
        $taskBeforeMain = [IO.File]::ReadAllText($taskBaselineMain).Replace("`r`n","`n")
        $taskAfterMain = [IO.File]::ReadAllText((Join-Path $taskWorkspace "foc2_app_$taskSlot/Core/Src/main.c")).Replace("`r`n","`n")
        # Exact, non-nested opt-in encoder guards. Restore their literal OFF
        # branches; the existing baseline comparison below remains unchanged.
        $taskEncoderGuard = '(?ms)^#if defined\(AS5047P_SPI_DMA\)\n(?<body>.*?)^#endif\n'
        if ([regex]::Matches($taskAfterMain,$taskEncoderGuard).Count -ne 11) { throw 'Expected exactly 11 simple encoder DMA guards' }
        $taskAfterMain = [regex]::Replace($taskAfterMain,$taskEncoderGuard,{
            param($taskMatch)
            $taskBody = $taskMatch.Groups['body'].Value
            if ($taskBody -match '(?m)^#(if|elif|endif)') { throw 'Nested encoder guard is not allowed by scope check' }
            $taskBranches = [regex]::Split($taskBody,'(?m)^#else\n')
            if ($taskBranches.Count -eq 1) { return '' }
            if ($taskBranches.Count -eq 2) { return $taskBranches[1] }
            throw 'Unexpected encoder guard branches'
        })
        $taskStackGuard = '(?s)#if defined\(ROUTER_READ_ONLY_NETWORK\)\n\s*/\* Hardware acceptance: 2 KiB overflowed.*?1024U,\n#else\n(\s*512U,\n)#endif\n'
        $taskOffMain = [regex]::Replace($taskAfterMain,$taskStackGuard,'$1')
        $taskRpcInclude = '#if defined\(ROUTER_READ_ONLY_RPC\)\n#include "pw_router_rpc.h"\n#endif\n'
        $taskRpcDispatch = '(?s)#if defined\(ROUTER_READ_ONLY_RPC\)\n\s*/\* Dedicated typed endpoint:.*?\n#endif\n'
        if ([regex]::Matches($taskOffMain,$taskRpcInclude).Count -ne 1 -or
            [regex]::Matches($taskOffMain,$taskRpcDispatch).Count -ne 1) { throw 'Expected exact guarded RPC include/dispatch' }
        $taskOffMain = [regex]::Replace($taskOffMain,$taskRpcInclude,'')
        $taskOffMain = [regex]::Replace($taskOffMain,$taskRpcDispatch,'')
        if ($taskOffMain -cne $taskBeforeMain) { throw "Unrelated main.c change: slot $taskSlot" }
        if ([regex]::Matches($taskAfterMain,$taskStackGuard).Count -ne 1) { throw 'Expected one guarded Router stack change' }
        Write-Output "PASS slot $taskSlot main.c guarded Router/RPC and encoder DMA changes; OFF preserved."
    }
}
