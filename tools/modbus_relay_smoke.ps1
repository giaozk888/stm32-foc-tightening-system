param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'

function Invoke-BoardCommand([System.IO.Ports.SerialPort]$Serial, [int]$Id, [string]$Command) {
    $Serial.Write("$Id $Command`r`n")
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line.StartsWith("$Id ")) {
                Write-Host $line
                if ($line -notmatch "^$Id OK ") { throw "Command failed: $line" }
                return $line
            }
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for request $Id ($Command)"
}

$serial = [System.IO.Ports.SerialPort]::new(
    $Port, $Baud, [System.IO.Ports.Parity]::None, 8,
    [System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$activeRelay = 0

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $status = Invoke-BoardCommand $serial 3940 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw 'Motor is not IDLE and fault-free; relay test aborted.'
    }
    $read = Invoke-BoardCommand $serial 3941 'MODBUS PROBE'
    if ($read -notmatch 'VALUE=0x0000') {
        throw 'Relays are not all OFF; relay test aborted.'
    }

    foreach ($relay in 1..4) {
        $id = 3940 + 10 * $relay
        $expected = 1 -shl ($relay - 1)
        $activeRelay = $relay
        $on = Invoke-BoardCommand $serial ($id + 2) "MODBUS RELAY $relay ON"
        if ($on -notmatch "RELAY=$relay STATE=ON ACK=1") { throw "Relay $relay ON was not acknowledged." }
        $read = Invoke-BoardCommand $serial ($id + 3) 'MODBUS PROBE'
        if ($read -notmatch "VALUE=0x([0-9A-Fa-f]+)" -or [Convert]::ToInt32($Matches[1], 16) -ne $expected) {
            throw "Relay $relay ON readback did not match 0x$($expected.ToString('X2'))."
        }
        $off = Invoke-BoardCommand $serial ($id + 4) "MODBUS RELAY $relay OFF"
        if ($off -notmatch "RELAY=$relay STATE=OFF ACK=1") { throw "Relay $relay OFF was not acknowledged." }
        $activeRelay = 0
        $read = Invoke-BoardCommand $serial ($id + 5) 'MODBUS PROBE'
        if ($read -notmatch 'VALUE=0x0000') { throw "Relay $relay did not return to OFF." }
    }

    $status = Invoke-BoardCommand $serial 3990 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw 'Final motor state is not IDLE and fault-free.'
    }
    Write-Host 'MODBUS RELAY 1-4 SMOKE PASS: each relay ON/OFF acknowledged and independently read back; all OFF.'
} finally {
    if ($serial.IsOpen) {
        if ($activeRelay -ne 0) {
            try { $null = Invoke-BoardCommand $serial 3998 "MODBUS RELAY $activeRelay OFF" }
            catch { Write-Warning "Could not confirm emergency OFF for relay $activeRelay`: $_" }
        }
        $serial.Close()
    }
    $serial.Dispose()
}
