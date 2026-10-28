param([switch]$Demo)
$ErrorActionPreference = 'Stop'
$rootDir = $PSScriptRoot
$configPath = Join-Path $rootDir 'config\local.json'
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw 'Configure config/local.json from config.example.json first.'
}
$settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($settings.analysis_only -ne $true) { throw 'This prototype only supports analysis_only=true.' }
$pythonPath = $settings.python_path
if (-not $pythonPath -or -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Configured private Python runtime is missing. No system Python fallback.'
}
$mode = if ($Demo) { 'demo' } else { 'gui' }
& $pythonPath -B (Join-Path $rootDir 'main.py') $mode
exit $LASTEXITCODE
