$ErrorActionPreference = 'Stop'
$taskWorkspace = Split-Path $PSScriptRoot -Parent
$taskCmake = 'C:\Program Files\CMake\bin\cmake.exe'
$taskCtest = 'C:\Program Files\CMake\bin\ctest.exe'
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;' + $env:PATH
Push-Location $taskWorkspace
try {
    & $taskCmake -S tests/as5047p_host -B tests/as5047p_host/out -G Ninja -D 'CMAKE_C_COMPILER=D:/Qt/Tools/mingw1310_64/bin/gcc.exe' -D 'CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
    if ($LASTEXITCODE -ne 0) { throw 'Encoder host configuration failed' }
    & $taskCmake --build tests/as5047p_host/out -j 4
    if ($LASTEXITCODE -ne 0) { throw 'Encoder host build failed' }
    & $taskCtest --test-dir tests/as5047p_host/out --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw 'Encoder host tests failed' }
    & './tests/as5047p_host/out/as5047p_dma_test_a.exe'
    if ($LASTEXITCODE -ne 0) { throw 'DMA FSM tests failed' }
    & './tests/router_network_host/check_scope.ps1'
    $taskGuard = '(?ms)^#if defined\(AS5047P_SPI_DMA\)\n(?<body>.*?)^#endif\n'
    $taskSlotBranches = @()
    foreach ($taskSlot in @('a','b')) {
        $taskMain = [IO.File]::ReadAllText((Join-Path $taskWorkspace "foc2_app_$taskSlot/Core/Src/main.c")).Replace("`r`n","`n")
        $taskMatches = [regex]::Matches($taskMain,$taskGuard)
        if ($taskMatches.Count -ne 11) { throw "Encoder guard count drift: $taskSlot" }
        $taskSlotBranches += (($taskMatches | ForEach-Object {
            ([regex]::Split($_.Groups['body'].Value,'(?m)^#else\n'))[0]
        }) -join "`n--encoder-branch--`n")
    }
    if ($taskSlotBranches[0] -cne $taskSlotBranches[1]) { throw 'A/B encoder integration drift' }
    $taskPort = [IO.File]::ReadAllText((Join-Path $taskWorkspace 'firmware_common/as5047p_dma_stm32.c'))
    $taskEngine = [IO.File]::ReadAllText((Join-Path $taskWorkspace 'firmware_common/as5047p_dma_engine.c'))
    if (($taskPort + $taskEngine) -match '\b(HAL_SPI_\w+|vTask\w*|xTask\w*|malloc|printf|snprintf)\s*\(') {
        throw 'Blocking/RTOS/logging API introduced into DMA driver'
    }
    Write-Output 'PASS: A/B encoder branches synchronized; no HAL SPI wait/RTOS/heap/logging calls in driver.'
    Write-Output 'PASS: simulated encoder logic and feature-OFF scope; no board access, no WCET claim.'
} finally { Pop-Location }
