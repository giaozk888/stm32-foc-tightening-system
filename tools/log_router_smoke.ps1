param([string]$Port = 'COM5', [int]$Baud = 115200)

$ErrorActionPreference = 'Stop'

function Read-Until($Serial, [scriptblock]$Match, [int]$TimeoutMs = 6000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    $lines = [System.Collections.Generic.List[string]]::new()
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line.Length -eq 0) { continue }
            $null = $lines.Add($line)
            if (& $Match $line) {
                return ,$lines.ToArray()
            }
        } catch [System.TimeoutException] {}
    }
    throw "Timed out waiting for matching Router/log response"
}

function Send-Local($Serial, [int]$Id, [string]$Command) {
    $Serial.Write("$Id $Command`r`n")
    return @(Read-Until $Serial { param($line) $line.StartsWith("$Id ") })
}

function Send-RoutedProtocol($Serial, [int]$Source, [int]$Sequence,
                             [string]$Payload) {
    $length = [Text.Encoding]::ASCII.GetByteCount($Payload)
    $Serial.Write("@R1 $Source 1 1 $Sequence 8 $length $Payload`r`n")
    return @(Read-Until $Serial {
        param($line)
        $line -match "^@R1 1 $Source 1 " -and $line.Contains($Payload.Split(' ')[0])
    })
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

    $initial = @(Send-Local $serial 4300 'LOG ROUTER STATUS')[-1]
    Write-Host $initial
    if ($initial -notmatch 'READY=1' -or $initial -notmatch 'TYPE=6') {
        throw "Log Router is not ready: $initial"
    }
    $initialMatch = [regex]::Match(
        $initial, 'CAPTURED=(\d+).*SENT=(\d+).*REMOTE_RX=(\d+)')
    if (-not $initialMatch.Success) {
        throw "Cannot parse initial Log Router counters: $initial"
    }
    $initialCaptured = [int]$initialMatch.Groups[1].Value
    $initialSent = [int]$initialMatch.Groups[2].Value
    $initialRemoteRx = [int]$initialMatch.Groups[3].Value

    $subscribePayload = '4301 LOG SUBSCRIBE INFO 30'
    $subscribeLines = @(Send-RoutedProtocol $serial 2 700 $subscribePayload)
    $subscribeReply = $subscribeLines |
        Where-Object { $_ -match '^@R1 1 2 1 ' -and $_ -match '4301 OK LOG SUBSCRIBE' } |
        Select-Object -Last 1
    Write-Host $subscribeReply
    if ($subscribeReply -notmatch 'NODE=2.*LEVEL=INFO.*TYPE=6') {
        throw "Routed subscription failed: $subscribeReply"
    }

    $serial.Write("4302 LOG TOKEN TEST 2`r`n")
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    $mirrored = [System.Collections.Generic.List[string]]::new()
    $commandReply = $null
    while ([DateTime]::UtcNow -lt $deadline -and
           (($mirrored.Count -lt 2) -or ($null -eq $commandReply))) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line.StartsWith('4302 ')) { $commandReply = $line }
            if ($line -match '^@R1 1 2 6 ' -and $line -match '\[PWT\].*\$') {
                $null = $mirrored.Add($line)
                Write-Host $line
            }
        } catch [System.TimeoutException] {}
    }
    Write-Host $commandReply
    if ($commandReply -notmatch 'ACCEPTED=2' -or $mirrored.Count -ne 2) {
        throw "Expected two mirrored tokenized records; got $($mirrored.Count)"
    }

    $routerStatus = @(Send-Local $serial 4303 'LOG ROUTER STATUS')[-1]
    Write-Host $routerStatus
    if ($routerStatus -notmatch 'SUBS=1' -or
        $routerStatus -notmatch 'DROP=0' -or
        $routerStatus -notmatch 'ROUTE_FAIL=0') {
        throw "Unexpected mirror diagnostics: $routerStatus"
    }
    $mirrorMatch = [regex]::Match($routerStatus, 'CAPTURED=(\d+).*SENT=(\d+)')
    if (-not $mirrorMatch.Success) {
        throw "Cannot parse mirror counters: $routerStatus"
    }
    if (([int]$mirrorMatch.Groups[1].Value -ne ($initialCaptured + 2)) -or
        ([int]$mirrorMatch.Groups[2].Value -ne ($initialSent + 2))) {
        throw "Mirror counters did not advance by two: $routerStatus"
    }

    $unsubscribePayload = '4304 LOG UNSUBSCRIBE'
    $unsubscribeLines = @(Send-RoutedProtocol $serial 2 701 $unsubscribePayload)
    $unsubscribeReply = $unsubscribeLines |
        Where-Object { $_ -match '^@R1 1 2 1 ' -and $_ -match '4304 OK LOG UNSUBSCRIBE' } |
        Select-Object -Last 1
    Write-Host $unsubscribeReply
    if ($unsubscribeReply -notmatch 'NODE=2') {
        throw "Routed unsubscribe failed: $unsubscribeReply"
    }

    Start-Sleep -Milliseconds 200
    $serial.DiscardInBuffer()
    $serial.Write("4305 LOG TOKEN TEST 1`r`n")
    $deadline = [DateTime]::UtcNow.AddSeconds(2)
    $postUnsubscribeMirror = 0
    $postReply = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line.StartsWith('4305 ')) { $postReply = $line }
            if ($line -match '^@R1 1 2 6 ') { $postUnsubscribeMirror++ }
        } catch [System.TimeoutException] {}
    }
    if ($postReply -notmatch 'ACCEPTED=1' -or $postUnsubscribeMirror -ne 0) {
        throw "Unsubscribe did not stop mirroring"
    }

    $remotePayload = '[PW][REMOTE][WARN] node2 diagnostic'
    $remoteLength = [Text.Encoding]::ASCII.GetByteCount($remotePayload)
    $serial.Write("@R1 2 1 6 702 8 $remoteLength $remotePayload`r`n")
    $remoteLines = @(Read-Until $serial {
        param($line)
        $line -eq "REMOTE LOG SRC=2 $remotePayload"
    })
    $remoteDisplay = $remoteLines |
        Where-Object { $_ -eq "REMOTE LOG SRC=2 $remotePayload" } |
        Select-Object -Last 1
    Write-Host $remoteDisplay
    if ($null -eq $remoteDisplay) {
        throw "Incoming Router type-6 log was not delivered locally"
    }

    $final = @(Send-Local $serial 4306 'LOG ROUTER STATUS')[-1]
    Write-Host $final
    $remoteMatch = [regex]::Match($final, 'REMOTE_RX=(\d+)')
    if ($final -notmatch 'SUBS=0' -or -not $remoteMatch.Success -or
        ([int]$remoteMatch.Groups[1].Value -ne ($initialRemoteRx + 1))) {
        throw "Subscriber was not removed: $final"
    }

    $runtime = @(Send-Local $serial 4307 'STATUS')[-1]
    Write-Host $runtime
    if ($runtime -notmatch 'MODE=IDLE' -or $runtime -notmatch 'FLT=0') {
        throw "Motor-control regression failed: $runtime"
    }
    Write-Host 'PW_LOG ROUTER MULTI-DEVICE SUBSCRIPTION SMOKE PASS'
}
finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
