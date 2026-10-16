$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskCmake = 'C:\Program Files\CMake\bin\cmake.exe'
$taskCtest = 'C:\Program Files\CMake\bin\ctest.exe'
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;' + $env:PATH
Push-Location $taskRoot
try {
    python tools/format_code.py
    if ($LASTEXITCODE -ne 0) { throw 'Formatting check failed' }
    foreach ($taskSuite in @('router_network_host','router_rpc_host','router_transfer_host')) {
        & $taskCmake -S "tests/$taskSuite" -B "tests/$taskSuite/build" -G Ninja `
            -D 'CMAKE_C_COMPILER=D:/Qt/Tools/mingw1310_64/bin/gcc.exe' `
            -D 'CMAKE_CXX_COMPILER=D:/Qt/Tools/mingw1310_64/bin/g++.exe' `
            -D 'CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
        if ($LASTEXITCODE -ne 0) { throw "Configure failed: $taskSuite" }
        & $taskCmake --build "tests/$taskSuite/build" -j 4
        if ($LASTEXITCODE -ne 0) { throw "Build failed: $taskSuite" }
        & $taskCtest --test-dir "tests/$taskSuite/build" --output-on-failure
        if ($LASTEXITCODE -ne 0) { throw "CTest failed: $taskSuite" }
    }
    python -m unittest discover -s router_network/tests -v
    if ($LASTEXITCODE -ne 0) { throw 'TCP/Python integration failed' }
    & ./tests/router_network_host/check_scope.ps1
    Write-Output 'HOST PASS: genuine Transfer client/server, forwarding, CRC, retry and reconnect; no board access.'
} finally { Pop-Location }
