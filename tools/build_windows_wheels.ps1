# Builds openal-py wheels for 64-bit Windows.
#
# Requires, on a 64-bit Windows machine:
#   - Visual Studio Build Tools (C++ workload)
#   - CMake on PATH (winget install Kitware.CMake)
#   - the Python Launcher (py.exe):
#       winget install 9NQ7512CXL7T -e --accept-package-agreements --disable-interactivity
#
# For each required version of Python:
#       py install 3.14
#
# Then, from the repo root:
#       .\tools\build_windows_wheels.ps1
#       .\tools\build_windows_wheels.ps1 -PythonVersions 3.11,3.12
#
# It snapshots the build inputs into a unique temporary workspace and builds
# libopenal plus a CPython wheel per version without modifying the checkout. It
# validates each with twine, and checks the win_amd64 platform tag.
# Upload with:
#       py -3.12 -m twine upload wheelhouse\windows.*\*.whl
[CmdletBinding()]
param(
    [string]$OpenAlSource = "",
    [string[]]$PythonVersions = @("3.10", "3.11", "3.12", "3.13", "3.14"),
    [string]$Wheelhouse = "",
    [switch]$SkipDependencyInstall,
    [switch]$KeepBuildArtifacts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Add-Type -AssemblyName System.IO.Compression.FileSystem

function Test-WheelContents {
    param([Parameter(Mandatory = $true)][string]$WheelPath)

    $Archive = [System.IO.Compression.ZipFile]::OpenRead($WheelPath)
    try {
        $Names = @($Archive.Entries | ForEach-Object { $_.FullName })
        $RuntimeDlls = @($Names | Where-Object { $_ -eq "openal_py/openal.dll" })
        if ($RuntimeDlls.Count -ne 1) {
            throw "Wheel must contain exactly one openal_py/openal.dll."
        }

        $Forbidden = @(
            $Names | Where-Object {
                $_ -match '\.h$' -or
                $_ -match '\.lib$' -or
                $_ -match '(^|/)build/.*meson'
            }
        )
        if ($Forbidden.Count -gt 0) {
            throw "Wheel contains forbidden files: $($Forbidden -join ', ')"
        }
    }
    finally {
        $Archive.Dispose()
    }
}

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($OpenAlSource)) {
    $OpenAlSource = Join-Path $RootDir "openal-soft"
}
$OpenAlSource = [System.IO.Path]::GetFullPath($OpenAlSource)

if ([string]::IsNullOrWhiteSpace($Wheelhouse)) {
    $Wheelhouse = Join-Path $RootDir "wheelhouse"
}
$Wheelhouse = [System.IO.Path]::GetFullPath($Wheelhouse)

$OpenAlHeader = Join-Path $OpenAlSource "include\AL\al.h"
if (-not (Test-Path -LiteralPath $OpenAlHeader -PathType Leaf)) {
    throw "openal-soft source not found: expected $OpenAlHeader"
}

foreach ($Cmd in @("py", "cmake")) {
    if (-not (Get-Command $Cmd -ErrorAction SilentlyContinue)) {
        throw "'$Cmd' was not found on PATH."
    }
}

if ($PythonVersions.Count -eq 0) {
    throw "Specify at least one Python version."
}
foreach ($Version in $PythonVersions) {
    & py "-$Version-64" -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) {
        throw "64-bit CPython $Version is not installed or not registered with py.exe."
    }
}

New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null
$RunId = [guid]::NewGuid().ToString("N")
$RunDir = Join-Path $Wheelhouse "windows.$RunId"
$WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) "openal-py.$RunId"
New-Item -ItemType Directory -Path $RunDir | Out-Null
New-Item -ItemType Directory -Path $WorkDir | Out-Null
$Project = Join-Path $WorkDir "project"
$NativeBuild = Join-Path $WorkDir "openal"
Write-Host "Wheel output: $RunDir"

try {
    $PrepareSource = Join-Path $PSScriptRoot "prepare_wheel_source.py"
    & py "-$($PythonVersions[0])-64" $PrepareSource $RootDir $Project --openal-source $OpenAlSource
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare isolated build inputs." }

    Write-Host "Building libopenal in $NativeBuild ..."
    cmake -S (Join-Path $Project "openal-soft") -B $NativeBuild -A x64 `
        -DCMAKE_BUILD_TYPE=Release `
        -DBUILD_SHARED_LIBS=ON `
        -DALSOFT_EXAMPLES=OFF `
        -DALSOFT_UTILS=OFF `
        -DALSOFT_TESTS=OFF
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed for openal-soft." }
    cmake --build $NativeBuild --config Release -j
    if ($LASTEXITCODE -ne 0) { throw "openal-soft build failed." }

    $OpenAlDll = Join-Path $NativeBuild "openal.dll"
    if (-not (Test-Path -LiteralPath $OpenAlDll -PathType Leaf)) {
        throw "openal-soft did not produce $OpenAlDll."
    }

    Push-Location $Project
    try {
        foreach ($Version in $PythonVersions) {
            Write-Host "Building openal-py for CPython $Version (64-bit)"
            if (-not $SkipDependencyInstall) {
                & py "-$Version-64" -m pip install --upgrade `
                    "meson-python>=0.16" "meson>=1.11" "ninja>=1.11" "cython>=3.0" `
                    build twine
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to install build dependencies for CPython $Version."
                }
            }

            $RawWheelDir = Join-Path $WorkDir "raw/$Version"
            New-Item -ItemType Directory -Force -Path $RawWheelDir | Out-Null
            & py "-$Version-64" -m build `
                --wheel `
                --no-isolation `
                --skip-dependency-check `
                --outdir $RawWheelDir `
                -C "setup-args=-Dopenal_libdir=$NativeBuild"
            if ($LASTEXITCODE -ne 0) {
                throw "Wheel build failed for CPython $Version."
            }

            $Wheels = @(Get-ChildItem -LiteralPath $RawWheelDir -Filter "*.whl" -File)
            if ($Wheels.Count -ne 1) {
                throw "Expected one wheel for CPython $Version; found $($Wheels.Count)."
            }
            $Wheel = $Wheels[0]
            if ($Wheel.Name -notmatch "-cp\d+-cp\d+-win_amd64\.whl$") {
                throw "Unexpected wheel platform tag: $($Wheel.Name)"
            }
            Test-WheelContents -WheelPath $Wheel.FullName
            & py "-$Version-64" -m twine check $Wheel.FullName
            if ($LASTEXITCODE -ne 0) {
                throw "Twine validation failed for $($Wheel.Name)."
            }
            Copy-Item -LiteralPath $Wheel.FullName -Destination $RunDir
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($KeepBuildArtifacts) {
        Write-Host "Build workspace retained: $WorkDir"
    }
    else {
        # Only this invocation's temporary directory is ever removed.
        Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Built Windows wheels:"
Get-ChildItem -LiteralPath $RunDir -Filter "*.whl" -File |
    Sort-Object Name |
    ForEach-Object { Write-Host "  $($_.FullName)" }
