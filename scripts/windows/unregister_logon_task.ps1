# Remove the logon task. Optionally delete %APPDATA%\ChronoScalp.
param(
    [switch]$RemoveUserData
)
$ErrorActionPreference = "Continue"
$taskName = "ChronoScalpRunner"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Output "Removed scheduled task $taskName (if it existed)."

$flag = $env:CHRONOSCALP_DELETE_USER_DATA
$installFlag = Join-Path (Split-Path -Parent $PSScriptRoot) "delete_user_data.flag"
if ($RemoveUserData -or $flag -eq "yes" -or (Test-Path -LiteralPath $installFlag)) {
    $homeDir = Join-Path $env:APPDATA "ChronoScalp"
    if (Test-Path -LiteralPath $homeDir) {
        Remove-Item -LiteralPath $homeDir -Recurse -Force
        Write-Output "Removed user data $homeDir"
    }
} else {
    Write-Output "Kept user data under %APPDATA%\ChronoScalp."
}
