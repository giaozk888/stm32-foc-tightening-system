param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'B',
    [ValidateRange(5, 300)][int]$Seconds = 120,
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
$requestId = 6100

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

function Read-Triple {
    $line = Invoke-Board 'ANALOG TRIPLE'
    if ($line -notmatch 'ANALOG TRIPLE V=1 R=\d+,\d+,\d+ M=\d+ MV=\d+ PR=(\d+),(\d+),(\d+) PM=(\d+),(\d+),(\d+) SP=\d+ D=(\d+) N=(\d+) E=(\d+)$') {
        throw "Triple data unavailable: $line"
    }
    $rawPeak = [Math]::Max([int]$Matches[1], [Math]::Max([int]$Matches[2], [int]$Matches[3]))
    $medSet = @([int]$Matches[4], [int]$Matches[5], [int]$Matches[6]) | Sort-Object
    return [pscustomobject]@{
        Line = $line
        PeakRaw = [uint32]$rawPeak
        PeakMedian = [uint32]$medSet[1]
        Disagree = [uint64]$Matches[7]
        Count = [uint64]$Matches[8]
        Errors = [uint64]$Matches[9]
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
    $volt = Invoke-Board 'ANALOG VOLT'
    if ($volt -notmatch 'VALID=1 .*VDDA_BOOT_MV=(\d+) .*DIV=25 PROTECT=0$') {
        throw "ADC reference unavailable: $volt"
    }
    $vddaMv = [uint32]$Matches[1]
    $initial = Read-Triple
    Write-Host "START $($initial.Line)"
    $previous = $initial
    $watch = [Diagnostics.Stopwatch]::StartNew()

    while ($watch.Elapsed.TotalSeconds -lt $Seconds) {
        Start-Sleep -Milliseconds $PollMs
        Assert-Safe
        $triple = Read-Triple
        if ($triple.Count -le $previous.Count) {
            throw "Triple count stopped: $($previous.Count) -> $($triple.Count)"
        }
        if ($triple.Errors -ne $initial.Errors) {
            throw "Triple sampling errors increased: $($triple.Line)"
        }
        Write-Host ('T+{0:N1}s {1}' -f $watch.Elapsed.TotalSeconds, $triple.Line)
        $previous = $triple
    }

    $status = Invoke-Board 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw "Motor state changed: $status"
    }
    Assert-Safe
    $peakRawMv = [Math]::Round([double]$previous.PeakRaw * $vddaMv * 25 / 4095)
    $peakMedianMv = [Math]::Round([double]$previous.PeakMedian * $vddaMv * 25 / 4095)
    Write-Host "TRIPLE OBSERVE COMPLETE: count $($initial.Count) -> $($previous.Count); errors $($initial.Errors) -> $($previous.Errors); disagreement $($initial.Disagree) -> $($previous.Disagree); peak raw $($previous.PeakRaw) (~$peakRawMv mV); peak median $($previous.PeakMedian) (~$peakMedianMv mV). Diagnostic only."
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
