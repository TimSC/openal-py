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
# It builds libopenal from the openal-soft submodule (into
# openal-soft\build, the meson default) and a CPython wheel per version,
# validates each with twine, and checks the win_amd64 platform tag.
# Upload with:
#       py -3.12 -m twine upload wheelhouse\*.whl
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

New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null
Get-ChildItem -LiteralPath $Wheelhouse -Filter "*.whl" -File |
    Remove-Item -Force

if (-not $KeepBuildArtifacts) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$OpenAlSource\build"
}

Write-Host "Building libopenal from $OpenAlSource ..."
cmake -S $OpenAlSource -B "$OpenAlSource\build" -A x64 `
    -DCMAKE_BUILD_TYPE=Release `
    -DBUILD_SHARED_LIBS=ON `
    -DENABLE_ALSOFT_EXAMPLES=OFF `
    -DBUILD_TESTING=OFF
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed for openal-soft." }
cmake --build "$OpenAlSource\build" --config Release -j
if ($LASTEXITCODE -ne 0) { throw "openal-soft build failed." }

$OpenAlDll = Join-Path $OpenAlSource "build\openal.dll"
if (-not (Test-Path -LiteralPath $OpenAlDll -PathType Leaf)) {
    throw "openal-soft did not produce $OpenAlDll."
}

Push-Location $RootDir
try {
    foreach ($Version in $PythonVersions) {
        Write-Host "Building openal-py for CPython $Version (64-bit)"

        & py "-$Version-64" -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -ne 0) {
            throw "64-bit CPython $Version is not installed or not registered with py.exe."
        }

        if (-not $SkipDependencyInstall) {
            & py "-$Version-64" -m pip install --upgrade `
                "meson-python>=0.16" "meson>=1.8" "ninja>=1.11" "cython>=3.0" `
                build twine
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to install build dependencies for CPython $Version."
            }
        }

        if (-not $KeepBuildArtifacts) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
                "build", "src\openal_py\*.c"
        }

        $RawWheelDir = Join-Path $env:TEMP "openal-py-$($Version.Replace('.', ''))"
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $RawWheelDir
        New-Item -ItemType Directory -Force -Path $RawWheelDir | Out-Null

        & py "-$Version-64" -m build `
            --wheel `
            --no-isolation `
            --skip-dependency-check `
            --outdir $RawWheelDir
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

        Copy-Item -LiteralPath $Wheel.FullName -Destination $Wheelhouse
    }
}
finally {
    Pop-Location
}

Write-Host "Built Windows wheels:"
Get-ChildItem -LiteralPath $Wheelhouse -Filter "*.whl" -File |
    Sort-Object Name |
    ForEach-Object { Write-Host "  $($_.FullName)" }
