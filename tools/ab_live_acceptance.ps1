param(
    [ValidateSet('Baseline', 'Boundary', 'Upgrade', 'Watch')][string]$Mode = 'Baseline',
    [string]$Port = 'COM5',
    [int]$Baud = 115200,
    [string]$Image,
    [Parameter(Mandatory)][string]$EvidenceDirectory,
    [ValidateSet('A', 'B')][string]$ExpectedFinalSlot,
    [switch]$PermitFlash,
    [switch]$StageOnly,
    [switch]$TestTrialUpdateLock
)
$ErrorActionPreference = 'Stop'
$taskEvidence = (Resolve-Path -LiteralPath $EvidenceDirectory).Path
if (-not $taskEvidence.StartsWith('D:\new project\safety_backups\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Evidence directory must be inside the workspace safety_backups directory.'
}
if ($Mode -in @('Boundary', 'Upgrade') -and -not $PermitFlash) { throw 'Explicit flash/reset permission required.' }
if ($TestTrialUpdateLock -and $Mode -ne 'Upgrade') { throw 'Trial update-lock test requires Upgrade mode.' }
if ($StageOnly -and ($Mode -ne 'Upgrade' -or $TestTrialUpdateLock)) { throw 'StageOnly requires Upgrade without a trial-lock test.' }
if (-not ('AbAcceptanceCrc' -as [type])) {
    Add-Type -TypeDefinition @'
public static class AbAcceptanceCrc {
    public static uint Calculate(byte[] bytes, int offset, int length) {
        uint value = 0xffffffffu;
        for (int i = offset; i < offset + length; ++i) {
            value ^= bytes[i];
            for (int n = 0; n != 8; ++n)
                value = (value >> 1) ^ ((value & 1) != 0 ? 0xedb88320u : 0u);
        }
        return value ^ 0xffffffffu;
    }
}
'@
}
$taskLog = Join-Path $taskEvidence ((Get-Date -Format 'HHmmss') + "-$Mode.log")
$taskSerial = [IO.Ports.SerialPort]::new($Port, $Baud, [IO.Ports.Parity]::None, 8, [IO.Ports.StopBits]::One)
$taskSerial.ReadTimeout = 100
$taskSerial.WriteTimeout = 2000
$taskSerial.DtrEnable = $false
$taskSerial.RtsEnable = $false
$script:taskRequest = 31000
function Log([string]$Text) {
    $record = '{0:o} {1}' -f [DateTime]::UtcNow, $Text
    Add-Content -LiteralPath $taskLog -Value $record -Encoding utf8
    Write-Host $Text
}
function Invoke-Board([string]$Command, [int]$TimeoutMs = 5000, [switch]$AllowError, [switch]$Quiet) {
    if ($Command -notmatch '^(FW (STATUS|END|ABORT|BEGIN [0-9]+ [0-9A-F]{8}|DATA [0-9A-F]{8} [0-9A-F]+)|ANALOG SAFE( STATUS)?|STATUS|PING|XFER STATUS)$') {
        throw "Out-of-scope command: $Command"
    }
    ++$script:taskRequest
    $id = $script:taskRequest
    if (-not $Quiet) { Add-Content -LiteralPath $taskLog -Value "TX $id $Command" -Encoding utf8 }
    $taskSerial.Write("$id $Command`r`n")
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $line = $taskSerial.ReadLine().Trim()
            if (-not $line) { continue }
            Add-Content -LiteralPath $taskLog -Value ("RX " + $line) -Encoding utf8
            if (-not $line.StartsWith("$id ")) { continue }
            if ($line.StartsWith("$id ERR ") -and -not $AllowError) { throw "Device refused: $line" }
            if ($line -notmatch "^$id (OK|ERR) ") { throw "Unexpected reply: $line" }
            return $line
        } catch [TimeoutException] {}
    }
    throw "Timeout: $Command"
}
function Ensure-Safe {
    $safe = Invoke-Board 'ANALOG SAFE STATUS'
    if ($safe -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0') { $safe = Invoke-Board 'ANALOG SAFE' }
    if ($safe -notmatch 'LATCHED=1 SD=0 MOE=0 FOC=0') { throw "Safe latch not proven: $safe" }
    Log $safe
}
function Ready-State {
    $fw = Invoke-Board 'FW STATUS'
    if ($fw -notmatch 'CURRENT=([AB]) TARGET=([AB]) ACTIVE=0' -or
        $fw -notmatch 'PENDING=- ATTEMPTS=0') { throw "Not confirmed/idle: $fw" }
    # Matches changes after each -match, so parse identities independently.
    $current = [regex]::Match($fw, 'CURRENT=([AB])').Groups[1].Value
    $confirmed = [regex]::Match($fw, 'CONFIRMED=([AB])').Groups[1].Value
    if ($current -ne $confirmed) { throw "Current image is not confirmed: $fw" }
    $status = Invoke-Board 'STATUS'
    if ($status -notmatch 'BUSY=0 MODE=IDLE' -or $status -notmatch 'START_REQ=0 FLT=0') {
        throw "Not fault-free and idle: $status"
    }
    Log $fw
    Log $status
    Ensure-Safe
    return $fw
}
function Await-Confirmed([string]$Slot, [int]$Seconds = 70, [switch]$CheckTrialLock) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $fw = Invoke-Board 'FW STATUS' 1200
            Log $fw
            if ($CheckTrialLock -and $fw -match 'HTRIAL=1') {
                Reject 'FW BEGIN 32 00000000' 'ERR 109 TRIAL_NOT_CONFIRMED'
                Log 'PASS: trial rejects a new FW BEGIN before any erase of the known-good opposite slot.'
                $CheckTrialLock = $false
            }
            if ($fw -match "CURRENT=$Slot TARGET=[AB] ACTIVE=0" -and
                $fw -match "CONFIRMED=$Slot PENDING=- ATTEMPTS=0") {
                Ensure-Safe
                if ($CheckTrialLock) { throw 'Trial window was missed; update-lock test not demonstrated.' }
                Log "PASS: final slot $Slot is confirmed and re-latched safe."
                return
            }
        } catch {
            if ($_.Exception.Message -notlike 'Timeout:*') { throw }
        }
        Start-Sleep -Milliseconds 300
    }
    throw "No confirmed slot $Slot before deadline. Inspect captured startup/health messages."
}
function Abort-And-Relatch([string]$Slot) {
    Log (Invoke-Board 'FW ABORT')
    Await-Confirmed $Slot 25
}
function Reject([string]$Command, [string]$Expected) {
    $reply = Invoke-Board $Command 5000 -AllowError
    Log $reply
    if ($reply -notmatch $Expected) { throw "Expected $Expected; got $reply" }
}
function Get-Image {
    if (-not $Image) { throw 'An explicit image is required.' }
    $path = (Resolve-Path -LiteralPath $Image).Path
    $bytes = [IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 32 -or $bytes.Length -gt 0x38000) { throw 'Image size is invalid.' }
    $sp = [BitConverter]::ToUInt32($bytes, 0)
    $reset = [BitConverter]::ToUInt32($bytes, 4)
    if ($sp -lt 0x20000000 -or $sp -gt 0x20020000 -or -not ($reset -band 1)) { throw 'Invalid vector.' }
    $entry = $reset -band 0xfffffffeL
    $slot = if ($entry -ge 0x08008000 -and $entry -lt 0x08040000) { 'A' }
        elseif ($entry -ge 0x08040000 -and $entry -lt 0x08078000) { 'B' } else { throw 'Entry outside either slot.' }
    $crc = [AbAcceptanceCrc]::Calculate($bytes, 0, $bytes.Length)
    $sha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    Log "IMAGE: slot=$slot bytes=$($bytes.Length) CRC=$($crc.ToString('X8')) SHA256=$sha path=$path"
    return @{ Bytes=$bytes; Slot=$slot; Crc=$crc; Path=$path }
}
try {
    $taskSerial.Open()
    $taskSerial.DiscardInBuffer()
    if ($Mode -eq 'Watch') {
        if (-not $ExpectedFinalSlot) { throw 'Expected final slot required.' }
        Await-Confirmed $ExpectedFinalSlot
        exit 0
    }
    $fw = Ready-State
    $current = [regex]::Match($fw, 'CURRENT=([AB])').Groups[1].Value
    $target = [regex]::Match($fw, 'TARGET=([AB])').Groups[1].Value
    if ($Mode -eq 'Baseline') { Log (Invoke-Board 'PING'); Log 'BASELINE PASS'; exit 0 }
    $imageInfo = Get-Image
    if ($imageInfo.Slot -ne $target -or $target -eq $current) { throw 'Image must target inactive slot.' }
    [byte[]]$bytes = $imageInfo.Bytes
    if ($Mode -eq 'Boundary') {
        Reject 'FW END' 'ERR .*FW_NOT_ACTIVE'
        Reject 'FW BEGIN 229377 00000000' 'ERR .*BAD_FW_BEGIN'
        [byte[]]$part = $bytes[0..31]
        $partCrc = [AbAcceptanceCrc]::Calculate($part, 0, $part.Length)
        Log (Invoke-Board ('FW BEGIN 32 {0:X8}' -f ($partCrc -bxor 1)) 15000)
        Reject 'FW END' 'ERR .*FW_INCOMPLETE'
        Reject 'FW BEGIN 32 00000000' 'ERR .*BUSY'
        $hex = [Convert]::ToHexString($part)
        Reject ("FW DATA 00000020 $hex") 'ERR .*FW_SEQUENCE EXPECT_OFFSET=00000000'
        Log (Invoke-Board ("FW DATA 00000000 $hex"))
        Reject ("FW DATA 00000000 $hex") 'ERR .*FW_SEQUENCE EXPECT_OFFSET=00000020'
        Reject 'FW END' 'ERR .*FW_CRC EXPECT='
        $after = Invoke-Board 'FW STATUS'; Log $after
        if ($after -notmatch "CONFIRMED=$current PENDING=- ATTEMPTS=0") { throw 'CRC failure altered boot state.' }
        Abort-And-Relatch $current
        Log (Invoke-Board ('FW BEGIN 32 {0:X8}' -f $partCrc) 15000)
        $part[0] = 0; $part[1] = 0; $part[2] = 0; $part[3] = 0
        Log (Invoke-Board ('FW DATA 00000000 ' + [Convert]::ToHexString($part)))
        Reject 'FW END' 'ERR .*BAD_TARGET_VECTOR'
        Abort-And-Relatch $current
        Log 'BOUNDARY PASS: inactive/end, size, busy, sequence, duplicate, incomplete, CRC, vector and abort recovery.'
        exit 0
    }
    Log (Invoke-Board ('FW BEGIN {0} {1:X8}' -f $bytes.Length, $imageInfo.Crc) 15000)
    $started = [DateTime]::UtcNow
    for ($offset = 0; $offset -lt $bytes.Length; $offset += 32) {
        $length = [Math]::Min(32, $bytes.Length - $offset)
        $hex = [Convert]::ToHexString($bytes, $offset, $length)
        $accepted = $false
        for ($attempt = 0; $attempt -lt 3 -and -not $accepted; ++$attempt) {
            try {
                $reply = Invoke-Board ('FW DATA {0:X8} {1}' -f $offset, $hex) 5000 -Quiet
                if ($reply -notmatch ('RX={0}/{1}(?:\s|$)' -f ($offset + $length), $bytes.Length)) {
                    throw "Write progress mismatch: $reply"
                }
                $accepted = $true
            } catch {
                if ($_.Exception.Message -notlike 'Timeout:*') { throw }
                # Never treat silence as acceptance or blindly erase/restart.
                # Query this exact transaction before retrying the same bytes.
                $state = Invoke-Board 'FW STATUS'
                Log $state
                if ($state -notmatch "CURRENT=$current TARGET=$target ACTIVE=1" -or
                    $state -notmatch ('SIZE={0} EXPECT=0x{1:X8}' -f $bytes.Length,$imageInfo.Crc) -or
                    $state -notmatch "CONFIRMED=$current PENDING=- ATTEMPTS=0") {
                    throw 'Transaction changed after DATA timeout; refusing recovery.'
                }
                $received = [int][regex]::Match($state,'\bRX=([0-9]+)').Groups[1].Value
                if ($received -eq $offset + $length) {
                    Log "PASS DATA recovery: lost/mismatched ACK; board confirms RX=$received"
                    $accepted = $true
                } elseif ($received -ne $offset) {
                    throw "Unexpected RX after timeout: $received"
                }
            }
        }
        if (-not $accepted) { throw "DATA not accepted after three attempts: offset=$offset" }
        if (($offset + $length) % 6400 -eq 0 -or $offset + $length -eq $bytes.Length) {
            Log ('DATA {0}/{1} ({2:F1}%)' -f ($offset + $length), $bytes.Length, (100.0 * ($offset + $length) / $bytes.Length))
        }
    }
    Log (Invoke-Board 'FW STATUS')
    if ($StageOnly) {
        Log 'STAGE PASS: inactive image uploaded; no FW END, trial reset or motion command sent.'
        exit 0
    }
    Log (Invoke-Board 'FW END' 15000)
    Log ('UPLOAD seconds={0:F2}' -f ([DateTime]::UtcNow - $started).TotalSeconds)
    if (-not $ExpectedFinalSlot) { $ExpectedFinalSlot = $target }
    Await-Confirmed $ExpectedFinalSlot 70 -CheckTrialLock:$TestTrialUpdateLock
    if ($ExpectedFinalSlot -ne $target) {
        # Do not mistake an unchanged old slot for a demonstrated rollback.
        $captured = [IO.File]::ReadAllText($taskLog)
        foreach ($attempt in @(1, 0)) {
            if ($captured -notmatch "CURRENT=$target .*CONFIRMED=$current PENDING=$target ATTEMPTS=$attempt .*HTRIAL=1 HOK=0 HSTABLE=0ms") {
                throw "Rollback evidence missing: unhealthy trial $target, attempts=$attempt"
            }
        }
        $failCount = [regex]::Matches($captured, 'RX BOOT HEALTH: FAIL timeout').Count
        if ($failCount -ne 2) { throw "Expected two health timeout resets; captured $failCount" }
        Log 'ROLLBACK PASS: two unhealthy trials, attempts 1 then 0, two timeout resets, original confirmed slot restored.'
    }
    Log 'UPGRADE/WATCH PASS'
} finally {
    if ($taskSerial.IsOpen) { $taskSerial.Close() }
    $taskSerial.Dispose()
}
