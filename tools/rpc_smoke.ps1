param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'

function Read-Reply([System.IO.Ports.SerialPort]$Serial, [int]$Id, [int]$TimeoutMs = 4000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line.StartsWith("$Id ")) { return $line }
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for request $Id"
}

function Invoke-Command([System.IO.Ports.SerialPort]$Serial, [int]$Id, [string]$Command) {
    $Serial.Write("$Id $Command`r`n")
    $reply = Read-Reply $Serial $Id
    Write-Host $reply
    if ($reply.StartsWith("$Id ERR ")) { throw $reply }
    return $reply
}

function Add-Fixed32([System.Collections.Generic.List[byte]]$Bytes, [uint32]$Value) {
    $Bytes.AddRange([BitConverter]::GetBytes($Value))
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

    $fw = Invoke-Command $serial 2100 'FW STATUS'
    $info = Invoke-Command $serial 2101 'RPC INFO'
    if ($info -notmatch 'READY=1 CH=(\d+) SERVICE=0x([0-9A-F]+) METHOD=0x([0-9A-F]+)') {
        throw "Could not parse RPC INFO: $info"
    }

    [byte]$channel = [byte]$Matches[1]
    [uint32]$service = [Convert]::ToUInt32($Matches[2], 16)
    [uint32]$method = [Convert]::ToUInt32($Matches[3], 16)
    [byte[]]$payload = [Text.Encoding]::ASCII.GetBytes('HELLO')

    $packet = [System.Collections.Generic.List[byte]]::new()
    $packet.Add(0x08); $packet.Add(0x00)       # REQUEST
    $packet.Add(0x10); $packet.Add($channel)  # channel_id
    $packet.Add(0x1D); Add-Fixed32 $packet $service
    $packet.Add(0x25); Add-Fixed32 $packet $method
    $packet.Add(0x2A); $packet.Add([byte]$payload.Length); $packet.AddRange($payload)
    $packet.Add(0x38); $packet.Add(0x01)       # call_id

    $hex = [Convert]::ToHexString($packet.ToArray())
    $rpc = Invoke-Command $serial 2102 "RPC CALL $hex"
    if ($rpc -notmatch 'OK RPC ([0-9A-F]+)$') { throw 'Missing RPC response packet' }
    if ($Matches[1] -notmatch '2A0548454C4C4F') { throw 'RPC payload echo mismatch' }

    Write-Host 'PW_RPC SMOKE PASS: request dispatched and correlated HELLO response returned.'
    $null = Invoke-Command $serial 2103 'RPC INFO'
    $null = Invoke-Command $serial 2104 'KVS STATUS'
    $null = Invoke-Command $serial 2105 'STATUS'
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
