param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [ValidateSet('A', 'B')][string]$ExpectedSlot = 'A'
)

$ErrorActionPreference = 'Stop'

function Read-Reply([System.IO.Ports.SerialPort]$Serial, [int]$Id, [int]$TimeoutMs = 5000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line.StartsWith("$Id ")) {
                Write-Host $line
                return $line
            }
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for request $Id"
}

function Invoke-Board([System.IO.Ports.SerialPort]$Serial, [int]$Id, [string]$Command) {
    $Serial.Write("$Id $Command" + [Environment]::NewLine)
    $reply = Read-Reply $Serial $Id
    if ($reply -notmatch "^$Id OK ") { throw "Command failed: $reply" }
    return $reply
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
    $fw = Invoke-Board $serial 4100 'FW STATUS'
    if ($fw -notmatch "CURRENT=$ExpectedSlot\b" -or
        $fw -notmatch "CONFIRMED=$ExpectedSlot\b" -or
        $fw -notmatch 'PENDING=-') {
        throw "Trial not confirmed in expected slot $ExpectedSlot."
    }
    $status = Invoke-Board $serial 4101 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw 'Motor is not IDLE and fault-free.'
    }
    $null = Invoke-Board $serial 4102 'MODBUS STATS'
    $read = Invoke-Board $serial 4103 'MODBUS PROBE'
    if ($read -notmatch 'VALUE=0x([0-9A-Fa-f]+)') {
        throw 'Could not parse relay status.'
    }
    $bits = [Convert]::ToInt32($Matches[1], 16)
    if (($bits -band (-bnot 15)) -ne 0) {
        throw 'Relays beyond channels 1-4 are ON; no automatic action taken.'
    }
    foreach ($relay in 1..4) {
        if (($bits -band (1 -shl ($relay - 1))) -ne 0) {
            Write-Warning "Relay $relay is ON; commanding OFF before the read-only test."
            $null = Invoke-Board $serial (4110 + $relay) "MODBUS RELAY $relay OFF"
        }
    }
    if ($bits -ne 0) {
        $read = Invoke-Board $serial 4115 'MODBUS PROBE'
        if ($read -notmatch 'VALUE=0x0000') {
            throw 'Relays did not all return to OFF.'
        }
    }

    # An unanswered slave creates a bounded 150 ms RTU timeout.
    # A following PING must still be handled by ProtocolTask first.
    $serial.Write("4104 MODBUS PROBE 9600 247 1 0 N" + [Environment]::NewLine)
    $serial.Write("4105 PING" + [Environment]::NewLine)
    $first = $null
    $seenPing = $false
    $seenTimeout = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $deadline -and (-not $seenPing -or -not $seenTimeout)) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line.StartsWith('4104 ') -or $line.StartsWith('4105 ')) {
                Write-Host $line
                if ($null -eq $first) { $first = $line }
                if ($line -eq '4105 OK PING PONG') { $seenPing = $true }
                if ($line -match '^4104 ERR MODBUS TIMEOUT ') { $seenTimeout = $true }
            }
        } catch [System.TimeoutException] {}
    }
    if (-not $seenPing -or -not $seenTimeout) {
        throw 'Expected PING and bounded Modbus timeout were not both received.'
    }
    if (-not $first.StartsWith('4105 ')) {
        throw 'PING did not overtake the unanswered Modbus request.'
    }
    $null = Invoke-Board $serial 4106 'MODBUS STATS'
    $null = Invoke-Board $serial 4107 'STATUS'
    foreach ($id in 4200..4224) {
        $read = Invoke-Board $serial $id 'MODBUS PROBE'
        if ($read -notmatch 'VALUE=0x0000') {
            throw "Repeated read $id did not report all relays OFF."
        }
    }
    $null = Invoke-Board $serial 4225 'MODBUS STATS'
    $status = Invoke-Board $serial 4226 'STATUS'
    if ($status -notmatch 'MODE=IDLE' -or $status -notmatch 'FLT=0') {
        throw 'Motor state changed during repeated reads.'
    }
    Write-Host 'MODBUS ASYNC SMOKE PASS: confirmed slot, readback, bounded timeout, responsive ProtocolTask.'
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
