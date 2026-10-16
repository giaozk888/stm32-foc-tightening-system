param(
    [Parameter(Mandatory)][string]$Dump,
    [Parameter(Mandatory)][string]$BaselineDump,
    [Parameter(Mandatory)][ValidateSet('A','B')][string]$ConfirmedSlot,
    [Parameter(Mandatory)][string]$Image,
    [string]$OppositeBaselineDump
)
$ErrorActionPreference = 'Stop'
if (-not ('AbFlashVerifyCrc' -as [type])) {
    Add-Type -TypeDefinition @'
public static class AbFlashVerifyCrc {
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
$taskDumpPath = (Resolve-Path -LiteralPath $Dump).Path
if (-not $taskDumpPath.StartsWith('D:\new project\safety_backups\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Dump must be in the workspace safety_backups directory.'
}
[byte[]]$taskFlash = [IO.File]::ReadAllBytes($taskDumpPath)
[byte[]]$taskBaseline = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $BaselineDump))
[byte[]]$taskImage = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Image))
if ($taskFlash.Length -ne 524288 -or $taskBaseline.Length -ne 524288) { throw 'Full 512 KiB dump required.' }
function Compare-Region([byte[]]$Left, [byte[]]$Right, [int]$Start, [int]$Length, [string]$Name) {
    for ($index = $Start; $index -lt $Start + $Length; ++$index) {
        if ($Left[$index] -ne $Right[$index]) { throw ('{0} mismatch at 0x{1:X8}' -f $Name, (0x08000000 + $index)) }
    }
    Write-Host "PASS unchanged: $Name ($Length bytes)"
}
Compare-Region $taskFlash $taskBaseline 0 0x8000 'Bootloader and reserved boot space'
Compare-Region $taskFlash $taskBaseline 0x78000 0x6800 'KVS and reserved data space'
Compare-Region $taskFlash $taskBaseline 0x7f800 0x800 'Parameter page'
$taskRecords = @()
foreach ($offset in @(0x7e800, 0x7f000)) {
    $words = @(for($index = 0; $index -lt 12; ++$index) { [BitConverter]::ToUInt32($taskFlash, $offset + 4 * $index) })
    $crc = [AbFlashVerifyCrc]::Calculate($taskFlash, $offset, 44)
    if ($words[0] -ne 0x424f4f54 -or $words[1] -ne 3 -or $words[11] -ne $crc) { throw ('Metadata invalid at 0x{0:X8}' -f (0x08000000 + $offset)) }
    $taskRecords += [pscustomobject]@{
        Address = ('0x{0:X8}' -f (0x08000000 + $offset)); Generation = $words[5]
        Confirmed = $words[2]; Pending = $words[3]; Attempts = $words[4]
        ASize = $words[6]; ACrc = ('{0:X8}' -f $words[7]); BSize = $words[8]; BCrc = ('{0:X8}' -f $words[9])
        RecordCrc = ('{0:X8}' -f $words[11]); RecordCrcValid = $true
    }
}
# This acceptance run does not cross the uint32 generation wrap boundary.
$latest = $taskRecords | Sort-Object Generation -Descending | Select-Object -First 1
$slotNumber = if($ConfirmedSlot -eq 'A') { 1 } else { 2 }
if ($latest.Confirmed -ne $slotNumber -or $latest.Pending -ne 0 -or $latest.Attempts -ne 0) { throw 'Latest metadata is not the expected confirmed/idle state.' }
$taskImageOffset = if($ConfirmedSlot -eq 'A') { 0x8000 } else { 0x40000 }
$taskImageCrc = '{0:X8}' -f [AbFlashVerifyCrc]::Calculate($taskImage, 0, $taskImage.Length)
$metadataSize = if($ConfirmedSlot -eq 'A') { $latest.ASize } else { $latest.BSize }
$metadataCrc = if($ConfirmedSlot -eq 'A') { $latest.ACrc } else { $latest.BCrc }
if ($metadataSize -ne $taskImage.Length -or $metadataCrc -ne $taskImageCrc) { throw 'Metadata image size/CRC differs from the expected image.' }
for($index=0; $index -lt $taskImage.Length; ++$index) {
    if($taskFlash[$taskImageOffset + $index] -ne $taskImage[$index]) { throw "Application readback differs at image offset $index" }
}
Write-Host "PASS image readback: slot=$ConfirmedSlot bytes=$($taskImage.Length) CRC=$taskImageCrc"
if ($OppositeBaselineDump) {
    [byte[]]$oppositeBaseline = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $OppositeBaselineDump))
    if($oppositeBaseline.Length -ne 524288) { throw 'Opposite baseline requires full dump.' }
    $otherOffset = if($ConfirmedSlot -eq 'A') { 0x40000 } else { 0x8000 }
    Compare-Region $taskFlash $oppositeBaseline $otherOffset 0x38000 'Opposite application slot'
}
$result = [pscustomobject]@{
    VerifiedUtc = [DateTime]::UtcNow.ToString('o'); Dump = $taskDumpPath
    DumpSha256 = (Get-FileHash -LiteralPath $taskDumpPath -Algorithm SHA256).Hash
    ConfirmedSlot = $ConfirmedSlot; ImageBytes = $taskImage.Length; ImageCrc = $taskImageCrc
    ImageSha256 = (Get-FileHash -LiteralPath $Image -Algorithm SHA256).Hash
    LatestGeneration = $latest.Generation; MetadataCopies = $taskRecords
    ProtectedRegionsUnchanged = $true; OppositeSlotChecked = [bool]$OppositeBaselineDump
}
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath ($taskDumpPath + '.verification.json') -Encoding utf8
$result | ConvertTo-Json -Depth 4
