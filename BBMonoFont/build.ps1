param(
    [switch]$RecreateVenv,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$venvDir = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

if ($RecreateVenv -and (Test-Path -LiteralPath $venvDir)) {
    $root = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
    $candidate = [IO.Path]::GetFullPath($venvDir)
    if (-not $candidate.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a directory outside the repository: $candidate"
    }
    Remove-Item -LiteralPath $candidate -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    $pythonArgs = @()
    if ($null -eq $python) {
        $python = Get-Command py -ErrorAction SilentlyContinue
        $pythonArgs = @('-3')
    }
    if ($null -eq $python) {
        throw 'Python 3.10 or newer is required.'
    }
    & $python.Source @pythonArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}

& $venvPython "$PSScriptRoot\scripts\verify_sources.py"
if ($LASTEXITCODE -ne 0) { throw 'Source font verification failed.' }

if (-not $SkipInstall) {
    & $venvPython -m pip install --disable-pip-version-check -r "$PSScriptRoot\requirements.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
}

& $venvPython "$PSScriptRoot\scripts\build_fonts.py"
if ($LASTEXITCODE -ne 0) { throw 'Font generation failed.' }

& $venvPython "$PSScriptRoot\scripts\verify_fonts.py" "$PSScriptRoot\fonts"
if ($LASTEXITCODE -ne 0) { throw 'Generated font verification failed.' }

$manifest = Join-Path $PSScriptRoot 'fonts\SHA256SUMS.txt'
$lines = Get-ChildItem -LiteralPath "$PSScriptRoot\fonts" -Filter 'BBMono-*.ttf' |
    Sort-Object Name | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        "$hash  $($_.Name)"
    }
[IO.File]::WriteAllLines($manifest, [string[]]$lines)

Write-Host ''
Write-Host 'BB Mono Font build completed:'
Get-ChildItem -LiteralPath "$PSScriptRoot\fonts" -Filter 'BBMono-*.ttf' |
    Sort-Object Name | ForEach-Object { Write-Host "  $($_.FullName)" }
