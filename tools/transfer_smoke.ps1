param([string]$Port = 'COM5', [int]$Baud = 115200)

$ErrorActionPreference = 'Stop'
$requestId = 2200

function Read-Reply($Serial, [int]$Id, [int]$TimeoutMs = 4000) {
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
function Add-Varint([System.Collections.Generic.List[byte]]$Out, [uint64]$Value) {
    do {
        [byte]$part = [byte]($Value -band 0x7f)
        $Value = $Value -shr 7
        if ($Value -ne 0) { $part = $part -bor 0x80 }
        $Out.Add($part)
    } while ($Value -ne 0)
}
function Add-VarintField($Out, [int]$Field, [uint64]$Value) {
    Add-Varint $Out ([uint64]($Field * 8)); Add-Varint $Out $Value
}
function Add-BytesField($Out, [int]$Field, [byte[]]$Value) {
    Add-Varint $Out ([uint64]($Field * 8 + 2)); Add-Varint $Out $Value.Length
    $Out.AddRange($Value)
}
function Add-Fixed32($Out, [uint32]$Value) {
    $Out.AddRange([BitConverter]::GetBytes($Value))
}
function New-OuterPacket([uint32]$Service, [uint32]$Method,
                         [byte[]]$Payload, [uint32]$CallId) {
    $p = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $p 1 0; Add-VarintField $p 2 1
    $p.Add(0x1d); Add-Fixed32 $p $Service
    $p.Add(0x25); Add-Fixed32 $p $Method
    Add-BytesField $p 5 $Payload
    Add-VarintField $p 7 $CallId
    return $p.ToArray()
}
function Invoke-Chunk($Serial, [uint32]$Service, [uint32]$Method,
                      [byte[]]$Chunk, [uint32]$CallId) {
    $packet = New-OuterPacket $Service $Method $Chunk $CallId
    $reply = Invoke-Line $Serial ("RPC CALL " + [Convert]::ToHexString($packet))
    if ($reply -notmatch 'OK RPC ([0-9A-F]+)$') { throw 'Missing RPC response' }
    return $Matches[1]
}
function New-StartChunk([uint32]$Session) {
    $p = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $p 10 1; Add-VarintField $p 11 1
    Add-VarintField $p 13 2; Add-VarintField $p 14 $Session
    return $p.ToArray()
}
function New-ConfirmChunk([uint32]$Session) {
    $p = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $p 10 7; Add-VarintField $p 12 $Session
    return $p.ToArray()
}
function New-DataChunk([uint32]$Session, [uint32]$Offset,
                       [byte[]]$Data, [uint32]$Remaining) {
    $p = [System.Collections.Generic.List[byte]]::new()
    if ($Offset -ne 0) { Add-VarintField $p 5 $Offset }
    Add-BytesField $p 6 $Data
    Add-VarintField $p 7 $Remaining
    Add-VarintField $p 10 0; Add-VarintField $p 12 $Session
    return $p.ToArray()
}
function Get-Crc32([byte[]]$Data) {
    [uint32]$crc = [uint32]::MaxValue
    foreach ($b in $Data) {
        $crc = $crc -bxor [uint32]$b
        for ($i = 0; $i -lt 8; $i++) {
            if ($crc -band 1) { $crc = ($crc -shr 1) -bxor [uint32]3988292384 }
            else { $crc = $crc -shr 1 }
        }
    }
    return [uint32]($crc -bxor [uint32]::MaxValue)
}

$serial = [System.IO.Ports.SerialPort]::new(
    $Port, $Baud, [System.IO.Ports.Parity]::None, 8,
    [System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200; $serial.WriteTimeout = 2000
$serial.DtrEnable = $false; $serial.RtsEnable = $false

try {
    $serial.Open(); Start-Sleep -Milliseconds 300; $serial.DiscardInBuffer()
    $null = Invoke-Line $serial 'XFER RESET'
    $info = Invoke-Line $serial 'XFER STATUS'
    if ($info -notmatch 'SERVICE=0x([0-9A-F]+) METHOD=0x([0-9A-F]+)') {
        throw "Cannot parse transfer IDs: $info"
    }
    [uint32]$service = [Convert]::ToUInt32($Matches[1], 16)
    [uint32]$method = [Convert]::ToUInt32($Matches[2], 16)
    [uint32]$session = 42
    [uint32]$call = 100

    $null = Invoke-Chunk $serial $service $method (New-StartChunk $session) $call; $call++
    $null = Invoke-Chunk $serial $service $method (New-ConfirmChunk $session) $call; $call++

    [byte[]]$data = [Text.Encoding]::ASCII.GetBytes(
        'Pigweed pw_transfer V2 chunk recovery on STM32G474 works.')
    [byte[]]$first = $data[0..31]
    $null = Invoke-Chunk $serial $service $method `
        (New-DataChunk $session 0 $first ($data.Length - 32)) $call; $call++

    # Deliberately send a wrong offset. The target must keep OFFSET=32 and
    # increment RETRANSMIT, then accept the corrected chunk.
    [byte[]]$tail = $data[32..($data.Length - 1)]
    $null = Invoke-Chunk $serial $service $method `
        (New-DataChunk $session 99 $tail 0) $call; $call++
    $recovery = Invoke-Line $serial 'XFER STATUS'
    if ($recovery -notmatch 'ACTIVE=1.*OFFSET=32.*RETRANSMIT=1') {
        throw "Retransmit recovery state mismatch: $recovery"
    }

    $null = Invoke-Chunk $serial $service $method `
        (New-DataChunk $session 32 $tail 0) $call
    $final = Invoke-Line $serial 'XFER STATUS'
    [uint32]$crc = Get-Crc32 $data
    $crcText = ('CRC32=0x{0:X8}' -f $crc)
    if ($final -notmatch "ACTIVE=0.*OFFSET=$($data.Length).*CHUNKS=2.*RETRANSMIT=1" -or
        $final -notmatch $crcText) {
        throw "Final transfer state mismatch: expected $crcText; got $final"
    }
    Write-Host ('PW_TRANSFER SMOKE PASS: {0} bytes, recovery=1, CRC32=0x{1:X8}' -f
                $data.Length, $crc)
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
