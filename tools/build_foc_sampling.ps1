$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskCmake='C:\Program Files\CMake\bin\cmake.exe'
$env:PATH='D:\software\arm\bin;' + $env:PATH
# Compilation only. Topology is deliberately UNCONFIRMED; no board access.
foreach($taskSlot in @('a','b')){
    Push-Location (Join-Path $taskRoot "foc2_app_$taskSlot")
    try {
        & $taskCmake --preset FocSamplingReadOnly -D 'CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
        if($LASTEXITCODE -ne 0){throw "Slot $taskSlot configure failed"}
        & $taskCmake --build --preset FocSamplingReadOnly -j 4
        if($LASTEXITCODE -ne 0){throw "Slot $taskSlot build failed"}
    } finally { Pop-Location }
}
Write-Output 'BUILD ONLY PASS: new A/B sampling binaries, unknown-topology fail-closed, no flash/reset/motor commands.'
