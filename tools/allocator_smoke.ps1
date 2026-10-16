param(
    [string]$Port = "COM5",
    [int]$Baud = 115200,
    [int]$BootWaitSeconds = 0
)

$ErrorActionPreference = 'Stop'

if ($BootWaitSeconds -gt 0) {
    Start-Sleep -Seconds $BootWaitSeconds
}

$serial = [System.IO.Ports.SerialPort]::new(
    $Port,
    $Baud,
    [System.IO.Ports.Parity]::None,
    8,
    [System.IO.Ports.StopBits]::One)
$serial.NewLine = "`n"
$serial.ReadTimeout = 300
$serial.WriteTimeout = 1000

function Invoke-Command([int]$RequestId, [string]$Command) {
    $serial.Write("$RequestId $Command`r`n")
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line.StartsWith("$RequestId ")) {
                Write-Host $line
                if ($line -notmatch "^$RequestId OK ") {
                    throw "Command failed: $line"
                }
                return $line
            }
        }
        catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for request $RequestId ($Command)"
}

try {
    $serial.Open()
    $serial.DiscardInBuffer()
    $status = Invoke-Command 3000 "ALLOC STATUS"
    $test = Invoke-Command 3001 "ALLOC TEST"
    $firmware = Invoke-Command 3002 "FW STATUS"
    $kvs = Invoke-Command 3003 "KVS STATUS"
    $rpc = Invoke-Command 3004 "RPC INFO"
    $runtime = Invoke-Command 3005 "STATUS"

    if ($test -notmatch "PASS=1" -or $test -notmatch "BEFORE=(\d+).+AFTER=\1") {
        throw "Allocator round-trip did not pass: $test"
    }
    if ($firmware -notmatch "CURRENT=([AB]).*CONFIRMED=\1" -or
        $firmware -notmatch "PENDING=-") {
        throw "A/B confirmation is not clean: $firmware"
    }
    if ($kvs -notmatch "READY=1" -or $rpc -notmatch "READY=1") {
        throw "Pigweed regression check failed: KVS='$kvs' RPC='$rpc'"
    }
    if ($runtime -notmatch "MODE=IDLE" -or $runtime -notmatch "FLT=0") {
        throw "Motor-control regression check failed: $runtime"
    }
    Write-Host "PW_ALLOCATOR SMOKE PASS"
}
finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
}
