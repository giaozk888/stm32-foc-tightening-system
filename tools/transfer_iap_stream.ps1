param(
    [Parameter(Mandatory = $true)][string]$Port,
    [Parameter(Mandatory = $true)][string]$Image,
    [int]$Baud = 115200,
    [switch]$AllowUpgrade,
    [switch]$AllowReset,
    [switch]$StageOnly,
    [switch]$VerboseLog,
    [string]$Python = 'python',
    [string]$Client = ''
)

$ErrorActionPreference = 'Stop'
if (-not $AllowUpgrade) {
    throw 'No hardware operation performed. Explicit -AllowUpgrade is required; isolate the power stage first.'
}
if ($StageOnly -and $AllowReset) { throw '-StageOnly and -AllowReset are mutually exclusive.' }
# Staging is now the default. No hand-written Transfer handshake/window/retry logic.
$scriptPath = Join-Path $PSScriptRoot 'firmware_transfer_iap.py'
$arguments = @($scriptPath, '--port', $Port, '--image', $Image, '--baud', $Baud, '--allow-upgrade')
if ($AllowReset) { $arguments += '--allow-reset' }
if ($VerboseLog) { $arguments += '--verbose' }
if ($Client) { $arguments += @('--client', $Client) }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw "Official UART firmware transfer failed (exit $LASTEXITCODE)." }
