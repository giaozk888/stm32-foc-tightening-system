param([string]$Port = 'COM5', [int]$Baud = 115200)

$ErrorActionPreference = 'Stop'
$requestId = 4000

function Read-Reply($Serial, [int]$Id, [int]$TimeoutMs = 5000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line.StartsWith("$Id ")) { return $line }
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for request $Id"
}
function Invoke-Line($Serial, [string]$Command) {
    $script:requestId++
    $Serial.Write("$script:requestId $Command`r`n")
    $reply = Read-Reply $Serial $script:requestId
    Write-Host $reply
    if ($reply.StartsWith("$script:requestId ERR ")) { throw $reply }
    return $reply
}

$serial = [IO.Ports.SerialPort]::new(
    $Port, $Baud, [IO.Ports.Parity]::None, 8, [IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $null = Invoke-Line $serial 'LOG CLEAR'
    $initial = Invoke-Line $serial 'LOG STATUS'
    if ($initial -notmatch 'READY=1.*LEVEL=INFO.*CAP=24.*HIST=0') {
        throw "Initial log state mismatch: $initial"
    }

    $null = Invoke-Line $serial 'LOG LEVEL ERROR'
    $filteredTest = Invoke-Line $serial 'LOG TEST 4'
    if ($filteredTest -notmatch 'ACCEPTED=0.*NOT_ENQUEUED=4') {
        throw "Level filter did not reject INFO burst: $filteredTest"
    }
    $filtered = Invoke-Line $serial 'LOG STATUS'
    if ($filtered -notmatch 'LEVEL=ERROR' -or $filtered -notmatch 'FILTERED=4') {
        throw "Filtered counter mismatch: $filtered"
    }

    $null = Invoke-Line $serial 'LOG LEVEL INFO'
    $burst = Invoke-Line $serial 'LOG TEST 64'
    if ($burst -notmatch 'REQUESTED=64') {
        throw "Burst command failed: $burst"
    }
    Start-Sleep -Milliseconds 500
    $afterBurst = Invoke-Line $serial 'LOG STATUS'
    if ($afterBurst -notmatch 'HIGH_WATER=24' -or
        $afterBurst -notmatch 'DROP_FULL=([1-9][0-9]*)' -or
        $afterBurst -notmatch 'HIST=16') {
        throw "Burst/drop accounting mismatch: $afterBurst"
    }

    $script:requestId++
    $dumpId = $script:requestId
    $serial.Write("$dumpId LOG DUMP`r`n")
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    $dumpLines = 0
    $dumpEnded = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line -match '^\[PW\]') { $dumpLines++ }
            if ($line -eq "$dumpId OK LOG DUMP END SENT=16") {
                Write-Host $line
                $dumpEnded = $true
                break
            }
        } catch [System.TimeoutException] {}
    }
    if (-not $dumpEnded -or $dumpLines -lt 16) {
        throw "LOG DUMP incomplete: lines=$dumpLines ended=$dumpEnded"
    }

    $null = Invoke-Line $serial 'LOG CLEAR'
    $cleared = Invoke-Line $serial 'LOG STATUS'
    if ($cleared -notmatch 'HIST=0.*ENQ=0.*SENT=0.*DROP_FULL=0') {
        throw "LOG CLEAR mismatch: $cleared"
    }
    $runtime = Invoke-Line $serial 'STATUS'
    if ($runtime -notmatch 'MODE=IDLE' -or $runtime -notmatch 'FLT=0') {
        throw "Motor-control regression: $runtime"
    }
    Write-Host 'PW_LOG BUFFER/DROP/DUMP SMOKE PASS'
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
