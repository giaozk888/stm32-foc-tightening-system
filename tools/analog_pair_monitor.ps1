param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'A',
    [ValidateRange(5, 300)][int]$Seconds = 60,
    [ValidateRange(500, 10000)][int]$PollMs = 5000
)

$ErrorActionPreference = 'Stop'
$serial = [System.IO.Ports.SerialPort]::new(
    $Port, $Baud, [System.IO.Ports.Parity]::None, 8,
    [System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$requestId = 5900

function Invoke-Board([string]$Command) {
    $script:requestId++
    $id = $script:requestId
    $serial.Write("$id $Command`r`n")
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $serial.ReadLine().Trim()
            if (-not $line.StartsWith("$id ")) { continue }
            if ($line -notmatch "^$id OK ") { throw "Command failed: $line" }
            return $line
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for $id $Command"
}

function Assert-Safe {
    $line = Invoke-Board 'ANALOG SAFE STATUS'
    if ($line -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1') {
        throw "Safe latch lost: $line"
    }
}

function Read-Pair {
    $line = Invoke-Board 'ANALOG PAIR'
    if ($line -notmatch 'VALID=1 LATCHED=1 .*COUNT=(\d+) ERR=(\d+) ADC=ADC2 PC4=CH5 PROTECT=0$') {
        throw "Pair data unavailable: $line"
    }
    return [pscustomobject]@{
        Line = $line
        Count = [uint64]$Matches[1]
        Errors = [uint64]$Matches[2]
    }
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()
    $fw = Invoke-Board 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-') {
        throw "Unexpected firmware state: $fw"
    }
    Assert-Safe
    $initial = Read-Pair
    Write-Host "START $($initial.Line)"
    $previous = $initial
    $watch = [Diagnostics.Stopwatch]::StartNew()

    while ($watch.Elapsed.TotalSeconds -lt $Seconds) {
        Start-Sleep -Milliseconds $PollMs
        Assert-Safe
        $pair = Read-Pair
        if ($pair.Count -le $previous.Count) {
            throw "Pair count stopped: $($previous.Count) -> $($pair.Count)"
        }
        if ($pair.Errors -ne $initial.Errors) {
            throw "Pair conversion errors increased: $($initial.Errors) -> $($pair.Errors)"
        }
        Write-Host ('T+{0:N1}s {1}' -f $watch.Elapsed.TotalSeconds, $pair.Line)
        $previous = $pair
    }

    $status = Invoke-Board 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw "Motor state changed: $status"
    }
    Assert-Safe
    Write-Host "PAIR OBSERVE COMPLETE: samples $($initial.Count) -> $($previous.Count), errors $($initial.Errors) -> $($previous.Errors)."
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
