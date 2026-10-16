$ErrorActionPreference = 'Stop'
$taskWorkspace = Split-Path $PSScriptRoot -Parent
$taskCmake = 'C:\Program Files\CMake\bin\cmake.exe'
$taskCtest = 'C:\Program Files\CMake\bin\ctest.exe'
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;' + $env:PATH
Push-Location $taskWorkspace
try {
    & $taskCmake -S tests/router_network_host -B tests/router_network_host/build -G Ninja -D 'CMAKE_C_COMPILER=D:/Qt/Tools/mingw1310_64/bin/gcc.exe' -D 'CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
    if ($LASTEXITCODE -ne 0) { throw 'C test configuration failed' }
    & $taskCmake --build tests/router_network_host/build -j 4
    if ($LASTEXITCODE -ne 0) { throw 'C test build failed' }
    & $taskCtest --test-dir tests/router_network_host/build --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw 'C Router tests failed' }
    & $taskCmake -S tests/router_rpc_host -B tests/router_rpc_host/build -G Ninja -D 'CMAKE_C_COMPILER=D:/Qt/Tools/mingw1310_64/bin/gcc.exe' -D 'CMAKE_CXX_COMPILER=D:/Qt/Tools/mingw1310_64/bin/g++.exe' -D 'CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
    if ($LASTEXITCODE -ne 0) { throw 'RPC test configuration failed' }
    & $taskCmake --build tests/router_rpc_host/build -j 4
    if ($LASTEXITCODE -ne 0) { throw 'RPC test build failed' }
    & $taskCtest --test-dir tests/router_rpc_host/build --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw 'Genuine Pigweed RPC tests failed' }
    python -m unittest discover -s router_network/tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Python Router tests failed' }
    & './tests/router_network_host/check_scope.ps1'
    Write-Output 'TEST PASS: Router/RPC CTest and Python tests; feature-OFF preservation; no board access.'
} finally { Pop-Location }
