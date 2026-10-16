param(
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [string]$Elf = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Elf)) {
    $Elf = Join-Path $projectRoot 'foc2_app_a\build\Debug\foc2.elf'
}
$Elf = (Resolve-Path -LiteralPath $Elf).Path
$tokenizerPy = (Resolve-Path -LiteralPath (Join-Path $projectRoot 'third_party\pigweed\pw_tokenizer\py')).Path
$elfPy = (Resolve-Path -LiteralPath (Join-Path $projectRoot 'third_party\pigweed\pw_elf\py')).Path
$requestId = 4100

function Read-UntilReply($Serial, [int]$Id, [int]$TimeoutMs = 6000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    $lines = [System.Collections.Generic.List[string]]::new()
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $Serial.ReadLine().Trim()
            if ($line.Length -ne 0) { $null = $lines.Add($line) }
            if ($line.StartsWith("$Id ")) { return $lines }
        } catch [System.TimeoutException] {}
    }
    throw "Timeout waiting for request $Id"
}

function Invoke-Line($Serial, [string]$Command) {
    $script:requestId++
    $Serial.Write("$script:requestId $Command`r`n")
    return Read-UntilReply $Serial $script:requestId
}

$serial = [IO.Ports.SerialPort]::new(
    $Port, $Baud, [IO.Ports.Parity]::None, 8, [IO.Ports.StopBits]::One)
$serial.ReadTimeout = 200
$serial.WriteTimeout = 2000
$serial.DtrEnable = $false
$serial.RtsEnable = $false

try {
    $serial.Open()
    Start-Sleep -Milliseconds 300
    $serial.DiscardInBuffer()

    $null = Invoke-Line $serial 'LOG CLEAR'
    $testLines = @(Invoke-Line $serial 'LOG TOKEN TEST 3')
    Start-Sleep -Milliseconds 300

    $tokenLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $testLines) {
        if ($line.StartsWith('[PWT]')) { $null = $tokenLines.Add($line) }
        Write-Host $line
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(3)
    while (($tokenLines.Count -lt 3) -and ([DateTime]::UtcNow -lt $deadline)) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line.StartsWith('[PWT]')) {
                $null = $tokenLines.Add($line)
                Write-Host $line
            }
        } catch [System.TimeoutException] {}
    }
    if ($tokenLines.Count -ne 3) {
        throw "Expected 3 tokenized records, received $($tokenLines.Count)"
    }

    $statusLines = @(Invoke-Line $serial 'LOG STATUS')
    $status = $statusLines[-1]
    Write-Host $status
    if ($status -notmatch 'TOK=3' -or
        $status -notmatch 'TBIN=([1-9][0-9]*)' -or
        $status -notmatch 'TB64=([1-9][0-9]*)') {
        throw "Tokenized counters are invalid: $status"
    }

    $oldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = "$tokenizerPy;$elfPy"
    try {
        $decoded = $tokenLines[0] |
            & python -m pw_tokenizer.detokenize base64 $Elf 2>$null |
            Out-String
    } finally {
        $env:PYTHONPATH = $oldPythonPath
    }
    $decoded = $decoded.Trim()
    Write-Host "DECODED: $decoded"
    if ($decoded -notmatch 'token burst index=0 value=-7' -or
        $decoded -notmatch 'module.*LOGTOK') {
        throw "Host detokenization failed: $decoded"
    }

    $runtimeLines = @(Invoke-Line $serial 'STATUS')
    $runtime = $runtimeLines[-1]
    Write-Host $runtime
    if ($runtime -notmatch 'MODE=IDLE' -or $runtime -notmatch 'FLT=0') {
        throw "Motor-control regression failed: $runtime"
    }
    Write-Host 'PW_LOG TOKENIZED/ELF DETOKENIZE SMOKE PASS'
}
finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
