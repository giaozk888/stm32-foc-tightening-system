param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'A',
    [ValidateRange(2, 120)][int]$Samples = 30,
    [ValidateRange(100, 10000)][int]$IntervalMs = 1000,
    [ValidateRange(0, 60000)][int]$ExpectedBusMv = 12000
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

function Assert-Idle([string]$Line) {
    if ($Line -notmatch 'MODE=IDLE' -or $Line -notmatch 'FLT=0') {
        throw "Motor is not IDLE and fault-free: $Line"
    }
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $fw = Invoke-Board 4700 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-') {
        throw "Expected confirmed slot ${ExpectedSlot}: $fw"
    }
    Assert-Idle (Invoke-Board 4701 'STATUS')
    $selftest = Invoke-Board 4702 'SELFTEST STATUS'
    if ($selftest -notmatch 'READY=1 MASK=0x000 .*ADC_CNT=(\d+) FOC_CNT=(\d+)') {
        throw "Preflight is not ready: $selftest"
    }
    $adcBefore = [uint64]$Matches[1]
    $focBefore = [uint64]$Matches[2]

    $pc4Min = [int]::MaxValue; $pc4Max = 0
    $pc5Min = [int]::MaxValue; $pc5Max = 0
    $busMin = [int]::MaxValue; $busMax = 0
    $tempMvMin = [int]::MaxValue; $tempMvMax = 0
    $sampleCounterFirst = $null; $sampleCounterLast = $null
    $errorsFirst = $null; $errorsLast = $null
    $watch = [System.Diagnostics.Stopwatch]::StartNew()

    for ($i = 0; $i -lt $Samples; $i++) {
        $live = Invoke-Board (4800 + $i) 'ANALOG LIVE'
        if ($live -notmatch 'VALID=1 PC4_RAW=(\d+) PC5_RAW=(\d+) AGE_MS=(\d+) SAMPLES=(\d+) ERRORS=(\d+) ADC=ADC2 IDLE_ONLY=1$') {
            throw "Invalid live sample $i`: $live"
        }
        $pc4 = [int]$Matches[1]; $pc5 = [int]$Matches[2]
        $age = [int]$Matches[3]
        $counter = [uint64]$Matches[4]
        $errors = [uint64]$Matches[5]

        $volt = Invoke-Board (5000 + $i) 'ANALOG VOLT'
        if ($volt -notmatch 'VALID=1 VBUS_EST_MV=(\d+) VTEMP_MV=(\d+) VDDA_BOOT_MV=(\d+) VREF_RAW=(\d+) AGE_MS=(\d+) DIV=25 PROTECT=0$') {
            throw "Invalid voltage sample $i`: $volt"
        }
        $bus = [int]$Matches[1]; $tempMv = [int]$Matches[2]
        $voltAge = [int]$Matches[5]
        if ($age -gt 500 -or $voltAge -gt 500 -or
            $pc4 -le 0 -or $pc4 -ge 4095 -or
            $pc5 -le 0 -or $pc5 -ge 4095) {
            throw "Stale or saturated sample $i."
        }
        if ($ExpectedBusMv -gt 0) {
            $lower = [int]($ExpectedBusMv * 0.90)
            $upper = [int]($ExpectedBusMv * 1.10)
            if ($bus -lt $lower -or $bus -gt $upper) {
                throw "VBUS outlier at sample $i`: PC4_RAW=$pc4, VBUS_EST_MV=$bus, expected $lower..$upper mV. Stop before firmware update or voltage sweep."
            }
        }
        if ($null -eq $sampleCounterFirst) {
            $sampleCounterFirst = $counter
            $errorsFirst = $errors
        }
        $sampleCounterLast = $counter
        $errorsLast = $errors
        $pc4Min = [Math]::Min($pc4Min, $pc4); $pc4Max = [Math]::Max($pc4Max, $pc4)
        $pc5Min = [Math]::Min($pc5Min, $pc5); $pc5Max = [Math]::Max($pc5Max, $pc5)
        $busMin = [Math]::Min($busMin, $bus); $busMax = [Math]::Max($busMax, $bus)
        $tempMvMin = [Math]::Min($tempMvMin, $tempMv); $tempMvMax = [Math]::Max($tempMvMax, $tempMv)
        if ($i -lt ($Samples - 1)) { Start-Sleep -Milliseconds $IntervalMs }
    }

    $selftest = Invoke-Board 4703 'SELFTEST STATUS'
    if ($selftest -notmatch 'READY=1 MASK=0x000 .*ADC_CNT=(\d+) FOC_CNT=(\d+)') {
        throw "Final preflight is not ready: $selftest"
    }
    $adcDelta = [uint64]$Matches[1] - $adcBefore
    $focDelta = [uint64]$Matches[2] - $focBefore
    Assert-Idle (Invoke-Board 4704 'STATUS')
    $watch.Stop()
    $elapsed = $watch.Elapsed.TotalSeconds
    $minimumProgress = [uint64][Math]::Floor($elapsed * 15000)
    if ($errorsLast -ne $errorsFirst -or
        $sampleCounterLast -lt ($sampleCounterFirst + ($Samples - 1) * $IntervalMs / 200) -or
        $adcDelta -lt $minimumProgress -or $focDelta -lt $minimumProgress) {
        throw "Stability check failed: errors $errorsFirst->$errorsLast, samples $sampleCounterFirst->$sampleCounterLast, ADC +$adcDelta, FOC +$focDelta in $elapsed s."
    }
    Write-Host ('ANALOG IDLE STABILITY PASS: {0} polls in {1:N1}s; PC4 raw {2}..{3}; PC5 raw {4}..{5}; VBUS est {6}..{7} mV; VTEMP pin {8}..{9} mV; errors {10}->{11}; ADC +{12}; FOC +{13}.' -f
        $Samples, $elapsed, $pc4Min, $pc4Max, $pc5Min, $pc5Max,
        $busMin, $busMax, $tempMvMin, $tempMvMax,
        $errorsFirst, $errorsLast, $adcDelta, $focDelta)
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
