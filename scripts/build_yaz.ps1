param(
    [string]$Version = "5.37.3",
    [string]$Sha256 = "975d7878b272cc999e5acbd02dc272a46607f95e6ee4f35ac655e8e4d333bf2b"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VendorRoot = Join-Path $ProjectRoot "build\vendor"
$Archive = Join-Path $VendorRoot "yaz-$Version.tar.gz"
$Source = Join-Path $VendorRoot "yaz-$Version"
$Url = "https://ftp.indexdata.com/pub/yaz/yaz-$Version.tar.gz"

New-Item -ItemType Directory -Force $VendorRoot | Out-Null
if (-not (Test-Path -LiteralPath $Archive)) {
    Invoke-WebRequest -UseBasicParsing $Url -OutFile $Archive
}
$ActualHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualHash -ne $Sha256.ToLowerInvariant()) {
    throw "YAZ source hash mismatch. Expected $Sha256, received $ActualHash."
}
if (-not (Test-Path -LiteralPath $Source)) {
    tar -xzf $Archive -C $VendorRoot
}

$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $VsWhere)) {
    throw "Visual Studio Build Tools were not found."
}
$VsRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $VsRoot) {
    throw "The Visual C++ x64 toolchain is required to build YAZ."
}
$DevCmd = Join-Path $VsRoot "Common7\Tools\VsDevCmd.bat"
$MakeCommand = @(
    "call `"$DevCmd`" -arch=x64 -host_arch=x64",
    "cd /d `"$(Join-Path $Source 'win')`"",
    "nmake /nologo DEBUG=0 BARCH=64 HAVE_TCL=0 HAVE_BISON=0 HAVE_ICONV=0 HAVE_ICU=0 HAVE_LIBXML2=0 HAVE_LIBXSLT=0 dll ztest"
) -join " && "
cmd.exe /d /s /c $MakeCommand
if ($LASTEXITCODE -ne 0) {
    throw "YAZ native build failed with exit code $LASTEXITCODE."
}

$Stage = Join-Path $ProjectRoot "native\yaz"
$ResolvedProject = [System.IO.Path]::GetFullPath($ProjectRoot)
$ResolvedStage = [System.IO.Path]::GetFullPath($Stage)
if (-not $ResolvedStage.StartsWith($ResolvedProject, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to replace native stage outside the project root: $ResolvedStage"
}
Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $Stage "include\yaz") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Stage "lib") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Stage "bin") | Out-Null
Copy-Item -Path (Join-Path $Source "src\yaz\*.h") -Destination (Join-Path $Stage "include\yaz")
Copy-Item -LiteralPath (Join-Path $Source "lib\yaz5.lib") -Destination (Join-Path $Stage "lib\yaz5.lib")
Copy-Item -LiteralPath (Join-Path $Source "bin\yaz5.dll") -Destination (Join-Path $Stage "bin\yaz5.dll")
Copy-Item -LiteralPath (Join-Path $Source "bin\yaz-ztest.exe") -Destination (Join-Path $Stage "bin\yaz-ztest.exe")

$PackageNative = Join-Path $ProjectRoot "src\z3950_search_for_marc\native"
New-Item -ItemType Directory -Force $PackageNative | Out-Null
Copy-Item -LiteralPath (Join-Path $Stage "bin\yaz5.dll") -Destination (Join-Path $PackageNative "yaz5.dll")

Push-Location $ProjectRoot
try {
    $env:YAZ_HOME = $Stage
    uv run python native\build_yaz_ffi.py
    if ($LASTEXITCODE -ne 0) {
        throw "CFFI adapter build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
