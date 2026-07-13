param(
    [string]$MsiPath = "dist\Z3950MarcSearch-2.0.0-x64.msi"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Msi = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $MsiPath))
$InstallDirectory = Join-Path $env:LOCALAPPDATA "Programs\Z39.50 MARC Search"
$Executable = Join-Path $InstallDirectory "Z3950MarcSearch.exe"
$UserData = Join-Path $env:LOCALAPPDATA "Z3950MarcSearch"
$LogDirectory = Join-Path $ProjectRoot "build\msi-test"
New-Item -ItemType Directory -Force $LogDirectory | Out-Null

try {
    $Install = Start-Process msiexec.exe `
        -ArgumentList "/i", "`"$Msi`"", "/qn", "/norestart", "/l*v", "`"$LogDirectory\install.log`"" `
        -WindowStyle Hidden -Wait -PassThru
    if ($Install.ExitCode -ne 0) { throw "MSI installation failed with $($Install.ExitCode)." }
    if (-not (Test-Path -LiteralPath $Executable)) { throw "Installed executable is missing." }

    $OriginalPath = $env:PATH
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $SelfTest = Start-Process $Executable -ArgumentList "--self-test" -Wait -PassThru
    if ($SelfTest.ExitCode -ne 0) {
        throw "Installed self-test failed with $($SelfTest.ExitCode)."
    }
    $env:PATH = $OriginalPath

    New-Item -ItemType Directory -Force $UserData | Out-Null
    Set-Content -LiteralPath (Join-Path $UserData "uninstall-test.txt") -Value "remove me"
}
finally {
    $Uninstall = Start-Process msiexec.exe `
        -ArgumentList "/x", "`"$Msi`"", "/qn", "/norestart", "/l*v", "`"$LogDirectory\uninstall.log`"" `
        -WindowStyle Hidden -Wait -PassThru
    if ($Uninstall.ExitCode -notin @(0, 1605)) {
        throw "MSI uninstall failed with $($Uninstall.ExitCode)."
    }
}

if (Test-Path -LiteralPath $InstallDirectory) { throw "Install directory remained after uninstall." }
if (Test-Path -LiteralPath $UserData) { throw "User data remained after default uninstall." }
Write-Host "MSI clean-install, self-test, and uninstall acceptance passed."
