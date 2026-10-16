param([string]$Port = 'COM5', [int]$Baud = 115200)

$ErrorActionPreference = 'Stop'
$requestId = 5200

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
function Add-Varint($Out, [uint64]$Value) {
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
function New-RpcPacket([uint32]$Type, [uint32]$Service, [uint32]$Method,
                       [byte[]]$Payload, [uint32]$CallId) {
    $packet = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $packet 1 $Type
    Add-VarintField $packet 2 1
    $packet.Add(0x1d); Add-Fixed32 $packet $Service
    $packet.Add(0x25); Add-Fixed32 $packet $Method
    if ($Payload.Length -ne 0) { Add-BytesField $packet 5 $Payload }
    Add-VarintField $packet 7 $CallId
    return $packet.ToArray()
}
function Invoke-RpcPacket($Serial, [uint32]$Type, [uint32]$Service,
                          [uint32]$Method, [byte[]]$Payload, [uint32]$CallId) {
    $packet = New-RpcPacket $Type $Service $Method $Payload $CallId
    return Invoke-Line $Serial ("RPC CALL " + [Convert]::ToHexString($packet))
}
function New-StartChunk([uint32]$Session) {
    $chunk = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $chunk 10 1; Add-VarintField $chunk 11 1
    Add-VarintField $chunk 13 2; Add-VarintField $chunk 14 $Session
    return $chunk.ToArray()
}
function New-ConfirmChunk([uint32]$Session) {
    $chunk = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $chunk 10 7; Add-VarintField $chunk 12 $Session
    return $chunk.ToArray()
}
function New-DataChunk([uint32]$Session, [uint32]$Offset,
                       [byte[]]$Data, [uint32]$Remaining) {
    $chunk = [System.Collections.Generic.List[byte]]::new()
    if ($Offset -ne 0) { Add-VarintField $chunk 5 $Offset }
    Add-BytesField $chunk 6 $Data; Add-VarintField $chunk 7 $Remaining
    Add-VarintField $chunk 10 0; Add-VarintField $chunk 12 $Session
    return $chunk.ToArray()
}
function Get-Crc32([byte[]]$Data) {
    [uint32]$crc = [uint32]::MaxValue
    foreach ($value in $Data) {
        $crc = $crc -bxor [uint32]$value
        for ($bit = 0; $bit -lt 8; $bit++) {
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
    if ($info -notmatch 'OFFICIAL_SERVICE=0x([0-9A-F]+) WRITE=0x([0-9A-F]+) STREAM=1') {
        throw "Official transfer stream is unavailable: $info"
    }
    [uint32]$service = [Convert]::ToUInt32($Matches[1], 16)
    [uint32]$method = [Convert]::ToUInt32($Matches[2], 16)
    [uint32]$call = 701
    [uint32]$session = 702

    # REQUEST opens pw.transfer.Transfer/Write. Transfer chunks then travel as
    # CLIENT_STREAM packets on the same call ID.
    $open = Invoke-RpcPacket $serial 0 $service $method ([byte[]]@()) $call
    if ($open -notmatch 'OK RPC ACCEPTED') { throw "Stream open failed: $open" }
    $null = Invoke-RpcPacket $serial 2 $service $method `
        (New-StartChunk $session) $call
    $null = Invoke-RpcPacket $serial 2 $service $method `
        (New-ConfirmChunk $session) $call

    [byte[]]$data = [Text.Encoding]::ASCII.GetBytes(
        'Official pw.transfer.Transfer Write stream works on STM32G474.')
    [byte[]]$first = $data[0..31]
    [byte[]]$tail = $data[32..($data.Length - 1)]
    $null = Invoke-RpcPacket $serial 2 $service $method `
        (New-DataChunk $session 0 $first ($data.Length - 32)) $call

    # Exercise the same recovery rule on the official stream transport.
    $null = Invoke-RpcPacket $serial 2 $service $method `
        (New-DataChunk $session 99 $tail 0) $call
    $recovery = Invoke-Line $serial 'XFER STATUS'
    if ($recovery -notmatch 'ACTIVE=1.*OFFSET=32.*RETRANSMIT=1') {
        throw "Streaming retransmit recovery failed: $recovery"
    }
    $null = Invoke-RpcPacket $serial 2 $service $method `
        (New-DataChunk $session 32 $tail 0) $call

    # CLIENT_REQUEST_COMPLETION closes the RPC stream and receives RESPONSE.
    $closed = Invoke-RpcPacket $serial 8 $service $method ([byte[]]@()) $call
    if ($closed -notmatch 'OK RPC [0-9A-F]+$') { throw "Stream close failed: $closed" }

    $final = Invoke-Line $serial 'XFER STATUS'
    [uint32]$crc = Get-Crc32 $data
    $crcText = ('CRC32=0x{0:X8}' -f $crc)
    if ($final -notmatch "ACTIVE=0.*OFFSET=$($data.Length).*CHUNKS=2.*RETRANSMIT=1" -or
        $final -notmatch $crcText) {
        throw "Final stream state mismatch: expected $crcText; got $final"
    }
    Write-Host ('PW_TRANSFER OFFICIAL STREAM PASS: {0} bytes, CRC32=0x{1:X8}' -f
                $data.Length, $crc)
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
