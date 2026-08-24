[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '1.0.0'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ProjectDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
$DistDir = Join-Path $ProjectDir 'dist'
$CacheDir = Join-Path $ProjectDir 'runtime\build-cache'
$BuildDir = Join-Path $DistDir ("build-{0}" -f $Version)
$PackageName = "TimedLauncher-v$Version-win64"
$PackageDir = Join-Path $BuildDir $PackageName
$ArchivePath = Join-Path $DistDir ("$PackageName.zip")
$ChecksumPath = Join-Path $DistDir 'SHA256SUMS.txt'
$ManifestPath = Join-Path $ProjectDir 'runtime_manifest.json'
$RequirementsPath = Join-Path $ProjectDir 'requirements.txt'

function Assert-ChildPath {
    param([string]$Child, [string]$Parent)
    $resolvedChild = [System.IO.Path]::GetFullPath($Child)
    $resolvedParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolvedChild.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe build path outside expected directory: $resolvedChild"
    }
}

function Remove-ExactDirectory {
    param([string]$Path, [string]$AllowedParent)
    if (Test-Path -LiteralPath $Path) {
        Assert-ChildPath -Child $Path -Parent $AllowedParent
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Get-NonEmptyConfiguredPaths {
    param($Value, [string]$Location = '$')
    $found = @()
    if ($null -eq $Value) {
        return $found
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string] -and $Value -isnot [pscustomobject]) {
        $index = 0
        foreach ($item in $Value) {
            $found += Get-NonEmptyConfiguredPaths -Value $item -Location "$Location[$index]"
            $index++
        }
        return $found
    }
    if ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) {
            $childLocation = "$Location.$($property.Name)"
            if ($property.Name -eq 'path' -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
                $found += $childLocation
            }
            $found += Get-NonEmptyConfiguredPaths -Value $property.Value -Location $childLocation
        }
    }
    return $found
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Missing runtime manifest: $ManifestPath"
}
if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
    throw "Missing requirements: $RequirementsPath"
}

$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$requirementsHash = (Get-FileHash -LiteralPath $RequirementsPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($requirementsHash -ne $manifest.requirements_sha256.ToLowerInvariant()) {
    throw 'requirements.txt changed without updating runtime_manifest.json'
}

$configPath = Join-Path $ProjectDir 'config\tasks.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$configuredPaths = @(Get-NonEmptyConfiguredPaths -Value $config)
if ($configuredPaths.Count -gt 0) {
    throw "Public config contains non-empty program paths: $($configuredPaths -join ', ')"
}

New-Item -ItemType Directory -Force -Path $DistDir, $CacheDir | Out-Null
Remove-ExactDirectory -Path $BuildDir -AllowedParent $DistDir
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

$releaseFiles = @(
    'README.md',
    'configure_launcher.bat',
    'launcher_environment.bat',
    'requirements.txt',
    'runtime_manifest.json',
    'scheduler_launcher.py',
    'setup_wizard.py',
    'start_launcher.bat',
    'start_launcher_hidden.bat',
    'stop_launcher.bat',
    'verify_runtime.py'
)
foreach ($relativePath in $releaseFiles) {
    Copy-Item -LiteralPath (Join-Path $ProjectDir $relativePath) -Destination (Join-Path $PackageDir $relativePath)
}

New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir 'config'), (Join-Path $PackageDir 'logs'), (Join-Path $PackageDir 'runtime') | Out-Null
Copy-Item -LiteralPath $configPath -Destination (Join-Path $PackageDir 'config\tasks.json')

$pythonUrl = [string]$manifest.python.url
$pythonHash = [string]$manifest.python.sha256
$pythonArchive = Join-Path $CacheDir ([System.IO.Path]::GetFileName($pythonUrl))
if (Test-Path -LiteralPath $pythonArchive) {
    $cachedHash = (Get-FileHash -LiteralPath $pythonArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($cachedHash -ne $pythonHash.ToLowerInvariant()) {
        Remove-Item -LiteralPath $pythonArchive -Force
    }
}
if (-not (Test-Path -LiteralPath $pythonArchive)) {
    Write-Host "Downloading Python $($manifest.python.version) from python.org..."
    Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonArchive
}
$downloadedHash = (Get-FileHash -LiteralPath $pythonArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($downloadedHash -ne $pythonHash.ToLowerInvariant()) {
    throw "Python archive SHA-256 mismatch: $downloadedHash"
}

$runtimeDir = Join-Path $PackageDir 'runtime\python'
Expand-Archive -LiteralPath $pythonArchive -DestinationPath $runtimeDir
$pythonExe = Join-Path $runtimeDir 'python.exe'
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Extracted Python runtime is incomplete'
}

Write-Host 'Installing pinned dependencies into the portable runtime...'
& $pythonExe -B -m pip install --disable-pip-version-check --no-cache-dir --no-compile --no-deps --upgrade --requirement (Join-Path $PackageDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw 'Portable dependency installation failed'
}
& $pythonExe -B -m pip check
if ($LASTEXITCODE -ne 0) {
    throw 'Portable dependency consistency check failed'
}

& $pythonExe -B (Join-Path $PackageDir 'verify_runtime.py')
if ($LASTEXITCODE -ne 0) {
    throw 'Portable runtime verification failed'
}
& $pythonExe -B (Join-Path $PackageDir 'setup_wizard.py') --validate-mapping
if ($LASTEXITCODE -ne 0) {
    throw 'Setup wizard mapping validation failed'
}

foreach ($entry in @('start_launcher.bat', 'start_launcher_hidden.bat', 'configure_launcher.bat')) {
    & cmd.exe /d /c call (Join-Path $PackageDir $entry) --check
    if ($LASTEXITCODE -ne 0) {
        throw "$entry validation failed"
    }
}

$pythonCaches = @(Get-ChildItem -LiteralPath $runtimeDir -Recurse -Directory -Filter '__pycache__' -Force)
foreach ($cache in ($pythonCaches | Sort-Object FullName -Descending)) {
    Remove-Item -LiteralPath $cache.FullName -Recurse -Force
}
$compiledFiles = @(
    Get-ChildItem -LiteralPath $runtimeDir -Recurse -File -Force |
        Where-Object { $_.Extension -eq '.pyc' -or $_.Extension -eq '.pyo' }
)
foreach ($compiledFile in $compiledFiles) {
    Remove-Item -LiteralPath $compiledFile.FullName -Force
}

$runtimeInfo = @(
    "TimedLauncher portable runtime",
    "Python: $($manifest.python.version) $($manifest.python.architecture)",
    "Source: $pythonUrl",
    "Python SHA-256: $pythonHash",
    "requirements.txt SHA-256: $requirementsHash"
) -join "`r`n"
[System.IO.File]::WriteAllText((Join-Path $runtimeDir 'TIMEDLAUNCHER_RUNTIME.txt'), $runtimeInfo + "`r`n", [System.Text.Encoding]::ASCII)

if (Test-Path -LiteralPath $ArchivePath) {
    Assert-ChildPath -Child $ArchivePath -Parent $DistDir
    Remove-Item -LiteralPath $ArchivePath -Force
}
Compress-Archive -LiteralPath $PackageDir -DestinationPath $ArchivePath -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText($ChecksumPath, "$archiveHash  $PackageName.zip`r`n", [System.Text.Encoding]::ASCII)

Remove-ExactDirectory -Path $BuildDir -AllowedParent $DistDir
Write-Host "RELEASE_ARCHIVE=$ArchivePath"
Write-Host "RELEASE_SHA256=$archiveHash"
