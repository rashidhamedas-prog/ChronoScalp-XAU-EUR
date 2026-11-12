# Seed %APPDATA%\ChronoScalp from the installed bundle. Does not overwrite .env.
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$homeDir = Get-ChronoScalpHome
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir "config") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir "data\state") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir "data\user") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir "logs") | Out-Null

$bundled = Join-Path $InstallDir "bundled\config"
$destConfig = Join-Path $homeDir "config"
if (Test-Path -LiteralPath $bundled) {
    Get-ChildItem -LiteralPath $bundled -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($bundled.Length).TrimStart("\", "/")
        $target = Join-Path $destConfig $relative
        if (-not (Test-Path -LiteralPath $target)) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target
        }
    }
}

$envFile = Join-Path $homeDir ".env"
$example = Join-Path $InstallDir "bundled\.env.example"
if (-not (Test-Path -LiteralPath $envFile) -and (Test-Path -LiteralPath $example)) {
    $text = Get-Content -LiteralPath $example -Raw -Encoding UTF8
    $text = [regex]::Replace($text, "(?m)^CHRONOSCALP_CONFIRM_LIVE=.*$", "CHRONOSCALP_CONFIRM_LIVE=no")
    if ($text -notmatch "CHRONOSCALP_CONFIRM_LIVE=") {
        $text = $text.TrimEnd() + "`r`nCHRONOSCALP_CONFIRM_LIVE=no`r`n"
    }
    Set-Content -LiteralPath $envFile -Value $text -Encoding UTF8
}

Write-Output "ChronoScalp user data: $homeDir"
Write-Output "CHRONOSCALP_CONFIRM_LIVE stays no until the operator edits .env."
