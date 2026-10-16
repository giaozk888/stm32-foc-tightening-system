$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$projectRoot = Split-Path $PSScriptRoot -Parent
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bundlePath = Join-Path $projectRoot "network_server/tencent-observations-$stamp.zip"
$entries = @(
    '__init__.py', 'schema.py', 'store.py', 'server.py',
    'index.html', 'app.js', 'style.css', 'README.md',
    'cloud/README.md', 'cloud/tencent-observations.service',
    'tests/test_server.py'
)
# Explicit whitelist: never package credentials, NVS, databases, build products or pycache.
$stream = [System.IO.File]::Open($bundlePath, [System.IO.FileMode]::CreateNew)
try {
    $archive = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        foreach ($entry in $entries) {
            $source = Join-Path $projectRoot "network_server/$entry"
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $source, "network_server/$entry") | Out-Null
        }
    } finally { $archive.Dispose() }
} finally { $stream.Dispose() }
Write-Output "Created server-only bundle: $bundlePath"
Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256
