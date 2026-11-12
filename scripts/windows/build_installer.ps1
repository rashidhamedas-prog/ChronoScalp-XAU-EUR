# Build ChronoScalp-Setup.exe on Windows.
# Order: venv -> pip requirements + PyInstaller -> onedir runner -> onedir panel -> Inno Setup.
# This script does not produce an executable on Linux. Do not commit a fake exe.
param(
    [switch]$SkipVenv
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not $SkipVenv) {
    if (-not (Test-Path -LiteralPath $Python)) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) {
            & py -3.11 -m venv (Join-Path $Root ".venv")
        } else {
            & python -m venv (Join-Path $Root ".venv")
        }
    }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Root "requirements.txt") pyinstaller
} elseif (-not (Test-Path -LiteralPath $Python)) {
    throw "SkipVenv was set but .venv\Scripts\python.exe is missing."
}

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\pyinstaller\chronoscalp-runner.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller runner build failed." }
& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\pyinstaller\chronoscalp-panel.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller panel build failed." }

$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup 6 (ISCC.exe) was not found. Install it, then re-run. Example: choco install innosetup -y"
}
& $iscc (Join-Path $Root "packaging\inno\ChronoScalp.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed." }

$setup = Join-Path $Root "dist\ChronoScalp-Setup.exe"
if (-not (Test-Path -LiteralPath $setup)) {
    throw "Expected installer was not written: $setup"
}
Write-Output "Built $setup"
