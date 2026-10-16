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
$requestId = 6700

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

function Read-Triple([string]$Command, [string]$Label) {
    $line = Invoke-Board $Command
    $pattern = "ANALOG $Label" + 'TRIPLE V=1 R=\d+,\d+,\d+ M=\d+ MV=\d+ PR=(\d+),(\d+),(\d+) PM=(\d+),(\d+),(\d+) SP=\d+ D=(\d+) N=(\d+) E=(\d+)$'
    if ($line -notmatch $pattern) { throw "Triple data unavailable: $line" }
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
    $first4 = Read-Triple 'ANALOG TRIPLE' ''
    $first5 = Read-Triple 'ANALOG PC5 TRIPLE' 'PC5 '
    Write-Host "START PC4 $($first4.Line)"
    Write-Host "START PC5 $($first5.Line)"
    $last4 = $first4
    $last5 = $first5
    $watch = [Diagnostics.Stopwatch]::StartNew()

    while ($watch.Elapsed.TotalSeconds -lt $Seconds) {
        Start-Sleep -Milliseconds $PollMs
        Assert-Safe
        $now4 = Read-Triple 'ANALOG TRIPLE' ''
        $now5 = Read-Triple 'ANALOG PC5 TRIPLE' 'PC5 '
        if ($now4.Count -le $last4.Count -or $now5.Count -le $last5.Count) {
            throw 'ADC triple counters stopped.'
        }
        if ($now4.Errors -ne $first4.Errors -or $now5.Errors -ne $first5.Errors) {
            throw "ADC triple sampling errors increased: PC4=$($now4.Line) PC5=$($now5.Line)"
        }
        Write-Host ('T+{0:N1}s PC4 {1}' -f $watch.Elapsed.TotalSeconds, $now4.Line)
        Write-Host ('T+{0:N1}s PC5 {1}' -f $watch.Elapsed.TotalSeconds, $now5.Line)
        $last4 = $now4
        $last5 = $now5
    }

    $status = Invoke-Board 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw "Motor state changed: $status"
    }
    Assert-Safe
    Write-Host "COMPARE COMPLETE: PC4 samples $($first4.Count)->$($last4.Count), disagreement $($first4.Disagree)->$($last4.Disagree), peak raw=$($last4.PeakRaw), peak median=$($last4.PeakMedian); PC5 samples $($first5.Count)->$($last5.Count), disagreement $($first5.Disagree)->$($last5.Disagree), peak raw=$($last5.PeakRaw), peak median=$($last5.PeakMedian). Diagnostic only."
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
