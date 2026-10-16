param(
    [ValidateSet('Inspect', 'CommitB', 'Text', 'Token')][string]$Action = 'Inspect',
    [string]$Port = 'COM5'
)
$ErrorActionPreference = 'Stop'
$serial = [IO.Ports.SerialPort]::new($Port, 115200, [IO.Ports.Parity]::None, 8, [IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$requestId = 12000
function Request([string]$command, [int]$timeoutMs = 6000) {
    $script:requestId++
    $id = $script:requestId
    $serial.Write("$id $command`r`n")
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line -match '^\[PW(T)?\]') { Write-Host $line }
            if ($line.StartsWith("$id ")) {
                Write-Host $line
                if (-not $line.StartsWith("$id OK ")) { throw $line }
                return $line
            }
        } catch [TimeoutException] {}
    }
    throw "No response for $command"
}
try {
    $serial.Open()
    Start-Sleep -Milliseconds 250
    $serial.DiscardInBuffer()
    $fw = Request 'FW STATUS'
    if ($Action -eq 'CommitB') {
        # This explicit operation is for the authorized, staged CAN-log image,
        # never a generic reset. Retain confirmed A as the bootloader fallback.
        if ($fw -notmatch 'CURRENT=A TARGET=B ACTIVE=1 RX=153680 SIZE=153680 EXPECT=0xB83F8B89 CONFIRMED=A PENDING=-') {
            throw 'Staged CAN-log image identity/slot mismatch; no reset sent.'
        }
        # FW BEGIN has already forced Fw_EnterSafeState. During ACTIVE=1
        # firmware permits only its restricted update/status set, so ANALOG SAFE
        # here is rejected. The staging script checked the latch before erase.
        $null = Request 'FW END' 20000
        # Boot health requires 5 s stable after ~3 s initialization, then an
        # automatic confirmation reset and another initialization. Poll instead
        # of assuming a fixed 8 s deadline means confirmation has completed.
        $confirmDeadline = [DateTime]::UtcNow.AddSeconds(25)
        do {
            Start-Sleep -Seconds 2
            $fw = Request 'FW STATUS'
            if ($fw -match 'CURRENT=B' -and $fw -match 'CONFIRMED=B PENDING=-') { break }
        } while ([DateTime]::UtcNow -lt $confirmDeadline)
        if ($fw -notmatch 'CURRENT=B' -or $fw -notmatch 'CONFIRMED=B PENDING=-') {
            $null = Request 'ANALOG SAFE'
            throw 'Trial B not confirmed; inspect boot health before proceeding.'
        }
    }
    $null = Request 'ANALOG SAFE'
    $safe = Request 'ANALOG SAFE STATUS'
    if ($safe -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0') { throw 'Safe latch not confirmed.' }
    $status = Request 'STATUS'
    if ($status -notmatch 'BUSY=0 MODE=IDLE' -or $status -notmatch 'FLT=0') { throw 'Not idle/fault free.' }
    if ($Action -eq 'Text') { $null = Request 'LOG TEST 3' }
    if ($Action -eq 'Token') { $null = Request 'LOG TOKEN TEST 1' }
    if ($Action -eq 'Text' -or $Action -eq 'Token') {
        $deadline = [DateTime]::UtcNow.AddSeconds(2)
        while ([DateTime]::UtcNow -lt $deadline) {
            try {
                $line = $serial.ReadLine().Trim()
                if ($line -match '^\[PW(T)?\]') { Write-Host $line }
            } catch [TimeoutException] {}
        }
    }
    $null = Request 'LOG STATUS'
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
