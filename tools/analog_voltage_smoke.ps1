param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'A',
    [int]$ExpectedBusMv = 12000
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
            Write-Host $line
            if ($line -notmatch "^$Id OK ") { throw "Command failed: $line" }
            return $line
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for $Id $Command"
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $fw = Invoke-Board 4600 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-') {
        throw "Expected confirmed slot $ExpectedSlot"
    }
    $status = Invoke-Board 4601 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw 'Motor must be IDLE and fault-free.'
    }
    $volt = Invoke-Board 4602 'ANALOG VOLT'
    if ($volt -notmatch 'VALID=1 VBUS_EST_MV=(\d+) VTEMP_MV=(\d+) VDDA_BOOT_MV=(\d+) VREF_RAW=(\d+) AGE_MS=(\d+) DIV=25 PROTECT=0$') {
        throw "Voltage estimate unavailable: $volt"
    }
    $bus = [int]$Matches[1]
    $tempVoltage = [int]$Matches[2]
    $vdda = [int]$Matches[3]
    $vrefRaw = [int]$Matches[4]
    $age = [int]$Matches[5]

    if ($age -gt 500 -or $vdda -lt 2400 -or $vdda -gt 3600 -or
        $vrefRaw -le 0 -or $tempVoltage -le 0) {
        throw 'Stale or implausible reference/temperature-channel reading.'
    }
    if ($ExpectedBusMv -gt 0) {
        $lower = [int]($ExpectedBusMv * 0.90)
        $upper = [int]($ExpectedBusMv * 1.10)
        if ($bus -lt $lower -or $bus -gt $upper) {
            throw "VBUS estimate $bus mV is outside the +/-10% diagnostic window around $ExpectedBusMv mV."
        }
    }
    Write-Host "ANALOG VOLT PASS: estimated bus $bus mV, VTEMP pin $tempVoltage mV, boot VDDA $vdda mV. Diagnostic only; no protection enabled."
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
