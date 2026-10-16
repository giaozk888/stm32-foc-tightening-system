param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [Parameter(Mandatory = $true)]
    [string]$Image,

    [int]$Baud = 115200,
    [switch]$VerboseLog,
    [switch]$StageOnly
)

$ErrorActionPreference = 'Stop'
$chunkSize = 32
$requestId = 5000

function Get-Crc32([byte[]]$Data) {
    [uint32]$crc = [uint32]::MaxValue
    foreach ($value in $Data) {
        $crc = $crc -bxor [uint32]$value
        for ($bit = 0; $bit -lt 8; $bit++) {
            if (($crc -band 1) -ne 0) {
                $crc = ($crc -shr 1) -bxor [uint32]3988292384
            } else {
                $crc = $crc -shr 1
            }
        }
    }
    return [uint32]($crc -bxor [uint32]::MaxValue)
}

function Read-MatchingResponse(
    [System.IO.Ports.SerialPort]$Serial,
    [int]$Id,
    [int]$TimeoutMs
) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($VerboseLog -and $line) {
                Write-Host "[RX] $line"
            }
            if ($line.StartsWith("$Id ")) {
                return $line
            }
        } catch [System.TimeoutException] {
            # Continue until the command-specific deadline.
        }
    }
    throw "Timeout waiting for request $Id"
}

function Invoke-IapCommand(
    [System.IO.Ports.SerialPort]$Serial,
    [string]$Command,
    [int]$TimeoutMs = 4000
) {
    $script:requestId++
    $id = $script:requestId
    $line = "$id $Command`r`n"
    if ($VerboseLog) {
        Write-Host "[TX] $($line.Trim())"
    }
    $Serial.Write($line)
    $response = Read-MatchingResponse $Serial $id $TimeoutMs
    if ($response.StartsWith("$id ERR ")) {
        throw $response
    }
    if (-not $response.StartsWith("$id OK ")) {
        throw "Unexpected response: $response"
    }
    return $response
}

$resolvedImage = (Resolve-Path -LiteralPath $Image).Path
[byte[]]$firmware = [System.IO.File]::ReadAllBytes($resolvedImage)
if ($firmware.Length -lt 8) {
    throw 'Firmware image is too small.'
}
$initialSp = [BitConverter]::ToUInt32($firmware, 0)
$resetVector = [BitConverter]::ToUInt32($firmware, 4) -band ([uint32]::MaxValue - 1)
if ($initialSp -lt 0x20000000 -or $initialSp -gt 0x20020000) {
    throw ('Invalid initial stack pointer: 0x{0:X8}' -f $initialSp)
}
$imageSlot = if ($resetVector -ge 0x08008000 -and $resetVector -lt 0x08040000) {
    'A'
} elseif ($resetVector -ge 0x08040000 -and $resetVector -lt 0x08078000) {
    'B'
} else {
    throw ('Reset vector is outside APP A/B slots: 0x{0:X8}' -f $resetVector)
}

[uint32]$crc32 = Get-Crc32 $firmware
Write-Host "Image : $resolvedImage"
Write-Host "Size  : $($firmware.Length) bytes"
Write-Host ('CRC32 : 0x{0:X8}' -f $crc32)
Write-Host "Slot  : $imageSlot (reset vector 0x$($resetVector.ToString('X8')))"

$serial = [System.IO.Ports.SerialPort]::new(
    $Port,
    $Baud,
    [System.IO.Ports.Parity]::None,
    8,
    [System.IO.Ports.StopBits]::One
)
$serial.ReadTimeout = 250
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false

try {
    $serial.Open()
    Start-Sleep -Milliseconds 250
    $serial.DiscardInBuffer()
    $serial.DiscardOutBuffer()

    $status = Invoke-IapCommand $serial 'FW STATUS'
    Write-Host $status
    $confirmedSlot = if ($status -match 'CONFIRMED=([AB])\b') { $Matches[1] } else { '' }
    $currentSlot = if ($status -match 'CURRENT=([AB])\b') { $Matches[1] } else { '' }
    $targetSlot = if ($status -match 'TARGET=([AB])\b') { $Matches[1] } else { '' }
    if ($currentSlot -ne $confirmedSlot -or
        $targetSlot -ne $imageSlot -or
        $targetSlot -eq $currentSlot -or
        $status -notmatch 'ACTIVE=0\b' -or
        $status -notmatch 'PENDING=-(?:\s|$)') {
        throw 'IAP preflight failed: image must target the inactive slot of a confirmed, idle APP with no pending trial.'
    }
    $safe = Invoke-IapCommand $serial 'ANALOG SAFE STATUS'
    Write-Host $safe
    if ($safe -notmatch 'LATCHED=1\b' -or
        $safe -notmatch 'SD=0\b' -or
        $safe -notmatch 'MOE=0\b' -or
        $safe -notmatch 'FOC=0\b') {
        throw 'Power stage is not latched safe; refusing to erase or program Flash.'
    }
    Write-Host (Invoke-IapCommand $serial (
        'FW BEGIN {0} {1:X8}' -f $firmware.Length, $crc32
    ) 60000)

    for ($offset = 0; $offset -lt $firmware.Length; $offset += $chunkSize) {
        $length = [Math]::Min($chunkSize, $firmware.Length - $offset)
        $hex = [Convert]::ToHexString($firmware, $offset, $length)
        $command = 'FW DATA {0:X8} {1}' -f $offset, $hex
        $accepted = $false

        for ($attempt = 1; $attempt -le 3 -and -not $accepted; $attempt++) {
            try {
                $null = Invoke-IapCommand $serial $command 4000
                $accepted = $true
            } catch {
                $message = $_.Exception.Message
                $nextOffset = $offset + $length
                if ($message -match 'EXPECT_OFFSET=([0-9A-Fa-f]+)') {
                    $expected = [Convert]::ToInt32($Matches[1], 16)
                    if ($expected -eq $nextOffset) {
                        $accepted = $true
                        break
                    }
                }
                if ($attempt -eq 3) {
                    throw
                }
                Start-Sleep -Milliseconds 150
            }
        }

        $done = $offset + $length
        if (($done -eq $firmware.Length) -or (($done % 3200) -eq 0)) {
            $percent = 100.0 * $done / $firmware.Length
            Write-Host ('DATA {0}/{1} ({2:F1}%)' -f $done, $firmware.Length, $percent)
        }
    }

    if ($StageOnly) {
        $staged = Invoke-IapCommand $serial 'FW STATUS'
        Write-Host $staged
        if ($staged -notmatch 'ACTIVE=1\b' -or
            $staged -notmatch ('RX={0}\b' -f $firmware.Length) -or
            $staged -notmatch ('SIZE={0}\b' -f $firmware.Length)) {
            throw 'Staged image byte count was not confirmed.'
        }
        Write-Host 'Image staged in inactive slot. FW END was NOT sent; no trial boot or reset.'
    } else {
        Write-Host (Invoke-IapCommand $serial 'FW END' 20000)
        Write-Host 'FW END accepted; device is resetting into the trial slot.'
    }
} finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
}
