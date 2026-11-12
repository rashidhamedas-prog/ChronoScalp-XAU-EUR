# Shared paths for the ChronoScalp Windows install. ASCII only (Windows PowerShell 5.1).

function Get-ChronoScalpScriptRoot {
    return $PSScriptRoot
}

function Get-ChronoScalpInstallRoot {
    $parent = Split-Path -Parent $PSScriptRoot
    $runner = Join-Path $parent "runner\ChronoScalpRunner.exe"
    if (Test-Path -LiteralPath $runner) {
        return $parent
    }
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-ChronoScalpHome {
    if ($env:CHRONOSCALP_HOME) {
        return $env:CHRONOSCALP_HOME
    }
    if (-not $env:APPDATA) {
        throw "APPDATA is not set. Cannot locate the ChronoScalp user directory."
    }
    return (Join-Path $env:APPDATA "ChronoScalp")
}

function Get-ChronoScalpRunnerExe {
    $installed = Join-Path (Get-ChronoScalpInstallRoot) "runner\ChronoScalpRunner.exe"
    if (Test-Path -LiteralPath $installed) {
        return $installed
    }
    return $null
}

function Get-ChronoScalpPanelExe {
    $installed = Join-Path (Get-ChronoScalpInstallRoot) "panel\ChronoScalpPanel.exe"
    if (Test-Path -LiteralPath $installed) {
        return $installed
    }
    return $null
}
