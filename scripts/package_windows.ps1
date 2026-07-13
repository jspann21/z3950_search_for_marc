$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    uv sync --locked --extra dev --extra package
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
    & "$PSScriptRoot\build_yaz.ps1"

    $Output = Join-Path $ProjectRoot "dist"
    foreach ($Generated in @("main.build", "main.dist", "main.onefile-build")) {
        $GeneratedPath = [System.IO.Path]::GetFullPath((Join-Path $Output $Generated))
        $ResolvedOutput = [System.IO.Path]::GetFullPath($Output)
        if (-not $GeneratedPath.StartsWith($ResolvedOutput, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to replace generated output outside dist: $GeneratedPath"
        }
        Remove-Item -LiteralPath $GeneratedPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    uv run python -m nuitka `
        --mode=standalone `
        --assume-yes-for-downloads `
        --enable-plugin=pyside6 `
        --include-windows-runtime-dlls=yes `
        --windows-console-mode=disable `
        --windows-icon-from-ico=src\z3950_search_for_marc\resources\app_icon.ico `
        --output-dir=$Output `
        --output-filename=Z3950MarcSearch.exe `
        --include-module=z3950_search_for_marc._yaz_native `
        --include-data-dir=src\z3950_search_for_marc\resources=z3950_search_for_marc\resources `
        --include-data-file=src\z3950_search_for_marc\native\yaz5.dll=z3950_search_for_marc\native\yaz5.dll `
        --include-data-file=LICENSE=LICENSE.txt `
        main.py
    if ($LASTEXITCODE -ne 0) { throw "Nuitka standalone build failed." }

    $PublishDir = Join-Path $Output "main.dist"
    & (Join-Path $PublishDir "Z3950MarcSearch.exe") --self-test
    if ($LASTEXITCODE -ne 0) { throw "Packaged application self-test failed." }

    $ToolDirectory = Join-Path $ProjectRoot "build\tools"
    New-Item -ItemType Directory -Force $ToolDirectory | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $ToolDirectory "wix.exe"))) {
        dotnet tool install wix --version 5.0.2 --tool-path $ToolDirectory
        if ($LASTEXITCODE -ne 0) { throw "WiX installation failed." }
    }
    & (Join-Path $ToolDirectory "wix.exe") extension add --global WixToolset.Util.wixext/5.0.2
    if ($LASTEXITCODE -ne 0) { throw "WiX Utility extension installation failed." }

    & (Join-Path $ToolDirectory "wix.exe") extension add --global WixToolset.UI.wixext/5.0.2
    if ($LASTEXITCODE -ne 0) { throw "WiX UI extension installation failed." }

    $VersionMatch = Select-String `
        -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") `
        -Pattern '^version\s*=\s*"([^"]+)"$'
    if (-not $VersionMatch) { throw "Could not read the application version from pyproject.toml." }
    $AppVersion = $VersionMatch.Matches[0].Groups[1].Value

    $InstallerBuildDirectory = Join-Path $ProjectRoot "build\installer"
    New-Item -ItemType Directory -Force $InstallerBuildDirectory | Out-Null
    $LicenseRtf = Join-Path $InstallerBuildDirectory "LICENSE.rtf"
    $LicenseText = Get-Content -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Raw
    $EscapedLicense = $LicenseText.Replace('\', '\\').Replace('{', '\{').Replace('}', '\}')
    $EscapedLicense = $EscapedLicense -replace "`r?`n", "\par`r`n"
    $Rtf = "{\rtf1\ansi\deff0{\fonttbl{\f0 Segoe UI;}}\fs18 $EscapedLicense}"
    Set-Content -LiteralPath $LicenseRtf -Value $Rtf -Encoding ascii

    $MsiName = "Z3950MarcSearch-$AppVersion-x64.msi"
    & (Join-Path $ToolDirectory "wix.exe") build installer\Product.wxs `
        -arch x64 `
        -ext WixToolset.Util.wixext `
        -ext WixToolset.UI.wixext `
        -d "AppVersion=$AppVersion" `
        -d "ApplicationIcon=$(Join-Path $ProjectRoot 'app_icon.ico')" `
        -d "LicenseRtf=$LicenseRtf" `
        -d "PublishDir=$PublishDir" `
        -o (Join-Path $Output $MsiName)
    if ($LASTEXITCODE -ne 0) { throw "MSI build failed." }
    $Msi = Join-Path $Output $MsiName
    $Digest = (Get-FileHash $Msi -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Digest  $MsiName" |
        Set-Content -LiteralPath (Join-Path $Output "SHA256SUMS.txt") -Encoding ascii
    Write-Host "MSI SHA-256: $Digest"
}
finally {
    Pop-Location
}
