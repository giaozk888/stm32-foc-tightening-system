param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'B',
    [ValidateRange(1000, 60000)][int]$ExpectedBusMv = 14000,
    [ValidateRange(2, 120)][int]$Samples = 30,
    [ValidateRange(100, 10000)][int]$IntervalMs = 1000
)

$ErrorActionPreference = 'Stop'
$serial = [System.IO.Ports.SerialPort]::new(
    $Port, $Baud, [System.IO.Ports.Parity]::None, 8,
    [System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false

function Invoke-Board([int]$Id, [string]$Command) {
    $serial.Write("$Id $Command`r`n")
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $serial.ReadLine().Trim()
            if (-not $line.StartsWith("$Id ")) { continue }
            if ($line -notmatch "^$Id OK ") { throw "Command failed: $line" }
            return $line
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for $Id $Command"
}

function Assert-Safe {
    $line = Invoke-Board 5600 'ANALOG SAFE STATUS'
    if ($line -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1') {
        throw "Safe latch lost: $line"
    }
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()
    $fw = Invoke-Board 5601 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-' -or $fw -notmatch 'ACTIVE=0') {
        throw "Unexpected firmware state: $fw"
    }
    Assert-Safe

    $busMin = [int]::MaxValue
    $busMax = 0
    $pc4Min = [int]::MaxValue
    $pc4Max = 0
    $countFirst = $null
    $countLast = $null
    $errorsFirst = $null
    $errorsLast = $null
    $lower = [int]($ExpectedBusMv * 0.90)
    $upper = [int]($ExpectedBusMv * 1.10)

    for ($i = 0; $i -lt $Samples; $i++) {
        $live = Invoke-Board (5700 + $i) 'ANALOG LIVE'
        if ($live -notmatch 'VALID=1 PC4_RAW=(\d+) PC5_RAW=(\d+) AGE_MS=(\d+) SAMPLES=(\d+) ERRORS=(\d+)') {
            throw "Invalid live sample $i`: $live"
        }
        $pc4 = [int]$Matches[1]
        $pc5 = [int]$Matches[2]
        $age = [int]$Matches[3]
        $count = [uint64]$Matches[4]
        $errors = [uint64]$Matches[5]
        $volt = Invoke-Board (5800 + $i) 'ANALOG VOLT'
        if ($volt -notmatch 'VALID=1 VBUS_EST_MV=(\d+) .*AGE_MS=(\d+) DIV=25 PROTECT=0$') {
            throw "Invalid voltage sample $i`: $volt"
        }
        $bus = [int]$Matches[1]
        $voltAge = [int]$Matches[2]
        if ($age -gt 500 -or $voltAge -gt 500 -or
            $pc4 -le 0 -or $pc4 -ge 4095 -or
            $pc5 -le 0 -or $pc5 -ge 4095 -or
            $bus -lt $lower -or $bus -gt $upper) {
            throw "Unsafe or implausible sample $i`: PC4=$pc4 PC5=$pc5 BUS=$bus mV; $live; $volt"
        }
        if ($null -eq $countFirst) {
            $countFirst = $count
            $errorsFirst = $errors
        }
        if ($errors -ne $errorsFirst) {
            throw "ADC2 sample error count increased at sample $i`: $errorsFirst->$errors"
        }
        $countLast = $count
        $errorsLast = $errors
        $busMin = [Math]::Min($busMin, $bus)
        $busMax = [Math]::Max($busMax, $bus)
        $pc4Min = [Math]::Min($pc4Min, $pc4)
        $pc4Max = [Math]::Max($pc4Max, $pc4)
        if ($i -lt ($Samples - 1)) { Start-Sleep -Milliseconds $IntervalMs }
    }

    Assert-Safe
    $status = Invoke-Board 5602 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw "Motor state changed: $status"
    }
    if ($countLast -le $countFirst) {
        throw "ADC2 sample count did not increase: $countFirst->$countLast"
    }
    Write-Host "ANALOG SAFE STABILITY PASS: $Samples polls; PC4 $pc4Min..$pc4Max; VBUS $busMin..$busMax mV; ADC2 count $countFirst->$countLast; errors $errorsFirst->$errorsLast; safe latch retained."
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
