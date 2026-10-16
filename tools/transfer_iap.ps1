param(
    [Parameter(Mandatory = $true)][string]$Port,
    [Parameter(Mandatory = $true)][string]$Image,
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'
$requestId = 12000

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
function Invoke-Line($Serial, [string]$Command, [int]$TimeoutMs = 5000) {
    $script:requestId++
    $Serial.Write("$script:requestId $Command`r`n")
    $reply = Read-Reply $Serial $script:requestId $TimeoutMs
    if ($reply.StartsWith("$script:requestId ERR ")) { throw $reply }
    return $reply
}
function Add-Varint($Out, [uint64]$Value) {
    do {
        [byte]$part = [byte]($Value -band 0x7f); $Value = $Value -shr 7
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
function New-Outer([uint32]$Service, [uint32]$Method,
                   [byte[]]$Payload, [uint32]$CallId) {
    $p = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $p 1 0; Add-VarintField $p 2 1
    $p.Add(0x1d); Add-Fixed32 $p $Service
    $p.Add(0x25); Add-Fixed32 $p $Method
    Add-BytesField $p 5 $Payload; Add-VarintField $p 7 $CallId
    return $p.ToArray()
}
function Invoke-Chunk($Serial, [uint32]$Service, [uint32]$Method,
                      [byte[]]$Chunk, [uint32]$CallId) {
    $outer = New-Outer $Service $Method $Chunk $CallId
    $hex = [Convert]::ToHexString($outer)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try { return Invoke-Line $Serial "RPC CALL $hex" 5000 }
        catch {
            if ($attempt -eq 3) { throw }
            Start-Sleep -Milliseconds 100
        }
    }
}
function New-Start([uint32]$Session) {
    $p = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $p 10 1; Add-VarintField $p 11 2
    Add-VarintField $p 13 2; Add-VarintField $p 14 $Session
    return $p.ToArray()
}
function New-Confirm([uint32]$Session) {
    $p = [System.Collections.Generic.List[byte]]::new()
    Add-VarintField $p 10 7; Add-VarintField $p 12 $Session
    return $p.ToArray()
}
function New-Data([uint32]$Session, [uint32]$Offset,
                  [byte[]]$Data, [uint32]$Remaining) {
    $p = [System.Collections.Generic.List[byte]]::new()
    if ($Offset -ne 0) { Add-VarintField $p 5 $Offset }
    Add-BytesField $p 6 $Data; Add-VarintField $p 7 $Remaining
    Add-VarintField $p 10 0; Add-VarintField $p 12 $Session
    return $p.ToArray()
}
function Get-Crc32([byte[]]$Data) {
    [uint32]$crc = [uint32]::MaxValue
    foreach ($value in $Data) {
        $crc = $crc -bxor [uint32]$value
        for ($bit = 0; $bit -lt 8; $bit++) {
            if ($crc -band 1) {
                $crc = ($crc -shr 1) -bxor [uint32]3988292384
            } else { $crc = $crc -shr 1 }
        }
    }
    return [uint32]($crc -bxor [uint32]::MaxValue)
}

$resolved = (Resolve-Path -LiteralPath $Image).Path
[byte[]]$firmware = [IO.File]::ReadAllBytes($resolved)
[uint32]$crc = Get-Crc32 $firmware
Write-Host "Image : $resolved"
Write-Host "Size  : $($firmware.Length) bytes"
Write-Host ('CRC32 : 0x{0:X8}' -f $crc)

$serial = [IO.Ports.SerialPort]::new(
    $Port, $Baud, [IO.Ports.Parity]::None, 8, [IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200; $serial.WriteTimeout = 2000
$serial.DtrEnable = $false; $serial.RtsEnable = $false

try {
    $serial.Open(); Start-Sleep -Milliseconds 300; $serial.DiscardInBuffer()
    Write-Host (Invoke-Line $serial 'FW STATUS')
    $info = Invoke-Line $serial 'XFER STATUS'
    if ($info -notmatch 'SERVICE=0x([0-9A-F]+) METHOD=0x([0-9A-F]+)') {
        throw "Cannot parse transfer IDs: $info"
    }
    [uint32]$service = [Convert]::ToUInt32($Matches[1], 16)
    [uint32]$method = [Convert]::ToUInt32($Matches[2], 16)
    $null = Invoke-Line $serial 'XFER RESET'
    Write-Host (Invoke-Line $serial (
        'FW BEGIN {0} {1:X8}' -f $firmware.Length, $crc) 15000)

    [uint32]$session = 77; [uint32]$call = 1000
    $null = Invoke-Chunk $serial $service $method (New-Start $session) $call; $call++
    $null = Invoke-Chunk $serial $service $method (New-Confirm $session) $call; $call++

    for ($offset = 0; $offset -lt $firmware.Length; $offset += 32) {
        $length = [Math]::Min(32, $firmware.Length - $offset)
        [byte[]]$part = New-Object byte[] $length
        [Array]::Copy($firmware, $offset, $part, 0, $length)
        [uint32]$remaining = $firmware.Length - $offset - $length
        $null = Invoke-Chunk $serial $service $method `
            (New-Data $session $offset $part $remaining) $call
        $call++
        if ((($offset + $length) % 3200) -eq 0 -or $remaining -eq 0) {
            Write-Host ('TRANSFER {0}/{1} ({2:N1}%)' -f
                ($offset + $length), $firmware.Length,
                (100.0 * ($offset + $length) / $firmware.Length))
        }
    }

    $xfer = Invoke-Line $serial 'XFER STATUS'
    Write-Host $xfer
    if ($xfer -notmatch "RESOURCE=2.*ACTIVE=0.*OFFSET=$($firmware.Length).*FLASH=1") {
        throw "Transfer did not stage the full image: $xfer"
    }
    $fw = Invoke-Line $serial 'FW STATUS'
    Write-Host $fw
    if ($fw -notmatch "ACTIVE=1 RX=$($firmware.Length) SIZE=$($firmware.Length)") {
        throw "FW context does not match transfer: $fw"
    }

    Write-Host (Invoke-Line $serial 'FW END' 15000)
    Write-Host 'PW_TRANSFER IAP accepted; device is resetting into trial slot.'
} catch {
    try { Write-Warning (Invoke-Line $serial 'FW ABORT') } catch {}
    throw
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
