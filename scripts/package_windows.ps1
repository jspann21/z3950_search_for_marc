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
    & (Join-Path $ToolDirectory "wix.exe") build installer\Product.wxs `
        -arch x64 `
        -ext WixToolset.Util.wixext `
        -d "PublishDir=$PublishDir" `
        -o (Join-Path $Output "Z3950MarcSearch-2.0.0-x64.msi")
    if ($LASTEXITCODE -ne 0) { throw "MSI build failed." }
    $Msi = Join-Path $Output "Z3950MarcSearch-2.0.0-x64.msi"
    $Digest = (Get-FileHash $Msi -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Digest  Z3950MarcSearch-2.0.0-x64.msi" |
        Set-Content -LiteralPath (Join-Path $Output "SHA256SUMS.txt") -Encoding ascii
    Write-Host "MSI SHA-256: $Digest"
}
finally {
    Pop-Location
}
