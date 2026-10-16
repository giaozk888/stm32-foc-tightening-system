param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'
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
    $serial.Write("4400 ANALOG BOOT`r`n")

    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $serial.ReadLine().Trim()
            if (-not $line.StartsWith('4400 ')) { continue }
            Write-Host $line
            if ($line -notmatch '^4400 OK ANALOG BOOT VALID=1 PC4_RAW=(\d+) PC5_RAW=(\d+) ADC=ADC2 LIVE=0$') {
                throw "Analog boot snapshot unavailable: $line"
            }

            $pc4 = [int]$Matches[1]
            $pc5 = [int]$Matches[2]
            if ($pc4 -le 0 -or $pc4 -ge 4095 -or
                $pc5 -le 0 -or $pc5 -ge 4095) {
                throw "ADC raw reading out of expected 12-bit range: PC4=$pc4 PC5=$pc5"
            }
            Write-Host ('PC5/PC4 raw ratio: {0:N3}; compare with meter ratio 1.11/0.48 = 2.313.' -f ($pc5 / $pc4))
            return
        } catch [System.TimeoutException] {}
    }
    throw 'Timeout waiting for ANALOG BOOT reply.'
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
