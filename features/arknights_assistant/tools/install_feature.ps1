param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][string]$LocalConfig
)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$targetRoot = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
if ((Split-Path -Leaf $targetRoot) -ne 'ArknightsAssistant') {
    throw 'Destination leaf must be ArknightsAssistant.'
}
if (Test-Path -LiteralPath $targetRoot) { throw 'Destination exists; refusing to overwrite files.' }
$settings = Get-Content -LiteralPath $LocalConfig -Raw -Encoding UTF8 | ConvertFrom-Json
if ($settings.analysis_only -ne $true) { throw 'Only analysis mode can be installed.' }
if (-not (Test-Path -LiteralPath $settings.python_path -PathType Leaf)) { throw 'Private Python missing.' }
if (-not (Test-Path -LiteralPath (Join-Path $settings.maa_dir 'MaaCore.dll') -PathType Leaf)) { throw 'MaaCore missing.' }
$folders = @('ark_assistant', 'examples', 'tests')
$files = @('main.py', 'README.md', 'start_assistant.bat', 'start_assistant.ps1', 'test_demo.bat', 'config\config.example.json')
$manifest = @()
foreach ($folder in $folders) {
    $manifest += @(Get-ChildItem -LiteralPath (Join-Path $sourceRoot $folder) -File -Recurse |
        Where-Object { $_.Extension -in @('.py','.json','.md') -and $_.FullName -notlike '*\__pycache__\*' } |
        ForEach-Object { $_.FullName.Substring($sourceRoot.Length + 1) })
}
$manifest += $files
foreach ($relative in $manifest) {
    $sourceFile = Join-Path $sourceRoot $relative
    $targetFile = [System.IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $targetFile.StartsWith($targetRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Destination escaped the intended directory.'
    }
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) { throw ('Missing source: ' + $relative) }
}
New-Item -ItemType Directory -Path $targetRoot | Out-Null
foreach ($relative in $manifest) {
    $sourceFile = Join-Path $sourceRoot $relative
    $targetFile = Join-Path $targetRoot $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $targetFile) -Force | Out-Null
    Copy-Item -LiteralPath $sourceFile -Destination $targetFile
    if ((Get-FileHash -LiteralPath $sourceFile).Hash -ne (Get-FileHash -LiteralPath $targetFile).Hash) {
        throw ('Copy hash mismatch: ' + $relative)
    }
}
Copy-Item -LiteralPath $LocalConfig -Destination (Join-Path $targetRoot 'config\local.json')
Write-Output ('INSTALLED_FILES=' + $manifest.Count)
Write-Output ('INSTALLED_AT=' + $targetRoot)
