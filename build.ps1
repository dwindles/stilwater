# Builds core (DFEngine.dll), the runtime (32-bit C++) and the launcher (.NET 8) into .\dist
# -Version sets the launcher's version (tools\release.ps1 passes the release's).
param([ValidateSet("Release", "Debug")] [string] $Configuration = "Release", [string] $Version = "")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dist = Join-Path $root "dist"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msbuild = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" | Select-Object -First 1
if (-not $msbuild) { throw "MSBuild not found; install Visual Studio 2022 (Build Tools) with C++" }

# core: the solution's Debug|Win32 configuration builds the shipping (Release) DFEngine.dll
& $msbuild "$root\core\Juiced Patch.sln" /m /p:Configuration=Debug /p:Platform=Win32 /nologo /v:minimal
if ($LASTEXITCODE) { throw "core build failed" }

cmake -S "$root\runtime" -B "$root\runtime\build" -G "Visual Studio 17 2022" -A Win32
if ($LASTEXITCODE) { throw "CMake configure failed" }
cmake --build "$root\runtime\build" --config $Configuration
if ($LASTEXITCODE) { throw "Runtime build failed" }

# The launcher publishes as one self-contained exe; drop files an older framework-dependent build left.
Remove-Item "$dist\StilwaterLauncher.*" -ErrorAction SilentlyContinue
$versionArgs = @()
if ($Version) { $versionArgs += "-p:Version=$Version" }
dotnet publish "$root\launcher\Stilwater.Launcher.csproj" -c $Configuration -o $dist --nologo @versionArgs
if ($LASTEXITCODE) { throw "Launcher build failed" }

Copy-Item "$root\runtime\build\$Configuration\stilwater.dll", "$root\runtime\build\$Configuration\stilwater-loader.exe" $dist -Force
Copy-Item "$root\core\Release\DFEngine.dll" $dist -Force
Write-Host "Built into $dist"
