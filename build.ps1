# Builds the runtime (32-bit C++) and the launcher (.NET 8) into .\dist
param([ValidateSet("Release", "Debug")] [string] $Configuration = "Release")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dist = Join-Path $root "dist"

cmake -S "$root\runtime" -B "$root\runtime\build" -G "Visual Studio 17 2022" -A Win32
if ($LASTEXITCODE) { throw "CMake configure failed" }
cmake --build "$root\runtime\build" --config $Configuration
if ($LASTEXITCODE) { throw "Runtime build failed" }

dotnet publish "$root\launcher\Stilwater.Launcher.csproj" -c $Configuration -o $dist --nologo
if ($LASTEXITCODE) { throw "Launcher build failed" }

Copy-Item "$root\runtime\build\$Configuration\stilwater.dll", "$root\runtime\build\$Configuration\stilwater-loader.exe" $dist -Force
Write-Host "Built into $dist"
