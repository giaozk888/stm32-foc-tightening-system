param(
    [string]$KeyPath = 'C:\Users\Administrator\AppData\Local\Temp\codex-lubancat-ssh-admin-20260928\id_ed25519'
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$archivePath = Join-Path $projectPath 'lubancat_hmi\log-touch-fix-20260930.zip'
$deployScript = Join-Path $PSScriptRoot 'lubancat-hmi-log-touch-deploy.sh'
foreach ($path in @($KeyPath, $archivePath, $deployScript)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file missing: $path" }
}
$sshOptions = @('-i', $KeyPath, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes')
& scp @sshOptions $archivePath 'root@192.168.137.10:/home/cat/log-touch-fix-20260930.zip'
if ($LASTEXITCODE -ne 0) { throw 'Source upload failed. HMI unchanged.' }
& scp @sshOptions $deployScript 'root@192.168.137.10:/home/cat/lubancat-hmi-log-touch-deploy.sh'
if ($LASTEXITCODE -ne 0) { throw 'Deployment script upload failed. HMI unchanged.' }
& ssh @sshOptions 'root@192.168.137.10' 'sh /home/cat/lubancat-hmi-log-touch-deploy.sh'
if ($LASTEXITCODE -ne 0) { throw 'Deployment did not complete. Inspect output and keep the previous HMI configuration.' }
