param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'A'
)

$ErrorActionPreference = 'Stop'

function Invoke-Board([System.IO.Ports.SerialPort]$Serial, [int]$Id, [string]$Command) {
    $Serial.Write("$Id $Command" + [Environment]::NewLine)
    $deadline = [DateTime]::UtcNow.AddSeconds(6)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line.StartsWith("$Id ")) {
                Write-Host $line
                if ($line -notmatch "^$Id OK ") { throw "Command failed: $line" }
                return $line
            }
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for $Id $Command"
}

$serial = [System.IO.Ports.SerialPort]::new(
    $Port, $Baud, [System.IO.Ports.Parity]::None, 8,
    [System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $fw = Invoke-Board $serial 4300 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-') {
        throw "Expected confirmed slot $ExpectedSlot."
    }
    $first = Invoke-Board $serial 4301 'SELFTEST STATUS'
    if ($first -notmatch 'READY=1 MASK=0x000 ' -or
        $first -notmatch 'ADC_CNT=(\d+) FOC_CNT=(\d+)') {
        throw 'Preflight is not ready or counters are missing.'
    }
    $adcBefore = [uint64]$Matches[1]
    $focBefore = [uint64]$Matches[2]
    Start-Sleep -Milliseconds 200
    $second = Invoke-Board $serial 4302 'SELFTEST STATUS'
    if ($second -notmatch 'READY=1 MASK=0x000 ' -or
        $second -notmatch 'ADC_CNT=(\d+) FOC_CNT=(\d+)') {
        throw 'Second preflight sample is not ready.'
    }
    $adcDelta = [uint64]$Matches[1] - $adcBefore
    $focDelta = [uint64]$Matches[2] - $focBefore
    if ($adcDelta -lt 2000 -or $focDelta -lt 2000) {
        throw "ADC/FOC did not progress sufficiently: $adcDelta / $focDelta"
    }
    $status = Invoke-Board $serial 4303 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw 'Motor is not IDLE and fault-free.'
    }
    Write-Host "SELFTEST SMOKE PASS: preflight ready; ADC +$adcDelta, FOC +$focDelta in >=200 ms."
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
