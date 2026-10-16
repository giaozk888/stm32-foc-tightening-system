param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'B',
    [ValidateRange(1000, 60000)][int]$ExpectedBusMv = 12000,
    [switch]$VerifyOnly
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

function Assert-Bus([string]$Line) {
    if ($Line -notmatch 'VALID=1 VBUS_EST_MV=(\d+) .*AGE_MS=(\d+) DIV=25 PROTECT=0$') {
        throw "Voltage reading invalid: $Line"
    }
    $bus = [int]$Matches[1]
    $age = [int]$Matches[2]
    $lower = [int]($ExpectedBusMv * 0.90)
    $upper = [int]($ExpectedBusMv * 1.10)
    if ($age -gt 500 -or $bus -lt $lower -or $bus -gt $upper) {
        throw "Voltage reading stale or outside $lower..$upper mV: $Line"
    }
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $fw = Invoke-Board 5500 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-' -or
        $fw -notmatch 'ACTIVE=0') {
        throw "Expected confirmed, idle slot $ExpectedSlot."
    }
    $status = Invoke-Board 5501 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0' -or
        $status -notmatch 'BUSY=0') {
        throw 'Motor is not IDLE and fault-free.'
    }
    Assert-Bus (Invoke-Board 5502 'ANALOG VOLT')
    $snapshot = Invoke-Board 5503 'FAULT SNAPSHOT'
    $filter = Invoke-Board 5504 'FAULT FILTER'
    if ($snapshot -notmatch 'VALID=0' -or $filter -notmatch 'VALID=0') {
        throw 'Unexpected prior current-trip snapshot; inspect before entering safe mode.'
    }
    $before = Invoke-Board 5505 'ANALOG SAFE STATUS'
    if ($VerifyOnly) {
        if ($before -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1') {
            throw 'Safe mode is not latched; do not change the supply voltage.'
        }
    } else {
        if ($before -notmatch 'LATCHED=0') {
            throw 'Safe mode is already latched; use -VerifyOnly.'
        }
        $entry = Invoke-Board 5506 'ANALOG SAFE'
        if ($entry -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1') {
            throw 'Safe-mode entry was not acknowledged.'
        }
    }
    Start-Sleep -Milliseconds 1200
    $after = Invoke-Board 5507 'ANALOG SAFE STATUS'
    if ($after -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1') {
        throw 'Safe-mode state did not remain latched.'
    }
    $live = Invoke-Board 5508 'ANALOG LIVE'
    if ($live -notmatch 'VALID=1 PC4_RAW=(\d+) PC5_RAW=(\d+) AGE_MS=(\d+) SAMPLES=(\d+) ERRORS=(\d+)') {
        throw 'ADC2 regular sampling is not available after PWM stop.'
    }
    $samples = [uint64]$Matches[4]
    $errors = [uint64]$Matches[5]
    Start-Sleep -Milliseconds 1100
    $live2 = Invoke-Board 5509 'ANALOG LIVE'
    if ($live2 -notmatch 'VALID=1 PC4_RAW=(\d+) PC5_RAW=(\d+) AGE_MS=(\d+) SAMPLES=(\d+) ERRORS=(\d+)') {
        throw 'ADC2 regular sampling became invalid after PWM stop.'
    }
    if ([uint64]$Matches[4] -le $samples -or [uint64]$Matches[5] -ne $errors) {
        throw 'ADC2 regular sampling did not continue cleanly after PWM stop.'
    }
    Assert-Bus (Invoke-Board 5510 'ANALOG VOLT')
    Write-Host 'ANALOG SAFE PASS: MCU reports SD=0, MOE=0, FOC=0; ADC2 voltage sampling continues. A reset clears the safe latch. Confirm the physical CTRL_SD pin before any voltage change.'
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
