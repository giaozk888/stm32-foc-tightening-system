$ErrorActionPreference = 'Stop'
$taskWorkspace = Split-Path $PSScriptRoot -Parent
$taskCmake = 'C:\Program Files\CMake\bin\cmake.exe'
$env:PATH = 'D:\software\arm\bin;' + $env:PATH
# Compilation only. Never flashes/resets a device or updates deployed images.
foreach ($taskSlot in @('a','b')) {
    Push-Location (Join-Path $taskWorkspace "foc2_app_$taskSlot")
    try {
        & $taskCmake --preset EncoderDmaReadOnly -D 'CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
        if ($LASTEXITCODE -ne 0) { throw "Slot $taskSlot configuration failed" }
        & $taskCmake --build --preset EncoderDmaReadOnly -j 4
        if ($LASTEXITCODE -ne 0) { throw "Slot $taskSlot build failed" }
    } finally { Pop-Location }
}
Write-Output 'BUILD PASS: separate EncoderDmaReadOnly A/B binaries only. Hardware timing remains unverified.'
