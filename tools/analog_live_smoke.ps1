param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'B'
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
            if ($line.StartsWith("$Id ")) {
                Write-Host $line
                if ($line -notmatch "^$Id OK ") { throw "Command failed: $line" }
                return $line
            }
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for $Id $Command"
}

function Parse-Analog([string]$Line) {
    if ($Line -notmatch 'VALID=1 PC4_RAW=(\d+) PC5_RAW=(\d+) AGE_MS=(\d+) SAMPLES=(\d+) ERRORS=(\d+) ADC=ADC2 IDLE_ONLY=1$') {
        throw "Invalid live analog reading: $Line"
    }
    return @{
        PC4 = [int]$Matches[1]; PC5 = [int]$Matches[2]
        Age = [int]$Matches[3]; Samples = [uint32]$Matches[4]
        Errors = [uint32]$Matches[5]
    }
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $fw = Invoke-Board 4500 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-') {
        throw "Expected confirmed slot $ExpectedSlot"
    }
    $status = Invoke-Board 4501 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw 'Motor must be IDLE and fault-free.'
    }
    $selftest1 = Invoke-Board 4502 'SELFTEST STATUS'
    if ($selftest1 -notmatch 'READY=1 MASK=0x000 .*ADC_CNT=(\d+) FOC_CNT=(\d+)') {
        throw 'Initial ADC/FOC preflight failed.'
    }
    $adcBefore = [uint32]$Matches[1]
    $focBefore = [uint32]$Matches[2]

    $first = Parse-Analog (Invoke-Board 4503 'ANALOG LIVE')
    Start-Sleep -Milliseconds 1100
    $second = Parse-Analog (Invoke-Board 4504 'ANALOG LIVE')
    $selftest2 = Invoke-Board 4505 'SELFTEST STATUS'
    if ($selftest2 -notmatch 'READY=1 MASK=0x000 .*ADC_CNT=(\d+) FOC_CNT=(\d+)') {
        throw 'Final ADC/FOC preflight failed.'
    }
    $adcDelta = [uint32]$Matches[1] - $adcBefore
    $focDelta = [uint32]$Matches[2] - $focBefore

    if ($second.Samples -lt ($first.Samples + 5) -or
        $second.Errors -ne $first.Errors -or
        $second.Age -gt 500 -or
        $second.PC4 -le 0 -or $second.PC4 -ge 4095 -or
        $second.PC5 -le 0 -or $second.PC5 -ge 4095 -or
        $adcDelta -lt 18000 -or $focDelta -lt 18000) {
        throw "Live analog/FOC progress failed: samples +$($second.Samples - $first.Samples), errors $($first.Errors)->$($second.Errors), ADC +$adcDelta, FOC +$focDelta"
    }
    Write-Host "ANALOG LIVE PASS: samples +$($second.Samples - $first.Samples), errors unchanged at $($second.Errors), ADC +$adcDelta, FOC +$focDelta."
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
