# Installs the launcher and runtime (dist\, without the core DLL) into <game>\Stilwater\, a fixed
# place for Steam's launch options to point at ("<game>\Stilwater\StilwaterLauncher.exe" %command%;
# the launcher's Settings page sets that up).
param(
    [string] $GameFolder = "E:\SteamLibrary\steamapps\common\Saints Row 2",
    [string] $Dist = (Join-Path $PSScriptRoot "..\dist")
)
$ErrorActionPreference = "Stop"

if (Get-Process -Name StilwaterLauncher -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$GameFolder*" }) {
    throw "Close the installed Stilwater launcher first."
}
if (-not (Test-Path (Join-Path $Dist "StilwaterLauncher.exe"))) { throw "$Dist has no launcher. Run build.ps1 first." }

$target = Join-Path $GameFolder "Stilwater"
New-Item -ItemType Directory -Force $target | Out-Null
Get-ChildItem $Dist -File | Where-Object Name -ne "DFEngine.dll" | Copy-Item -Destination $target -Force
if (Test-Path (Join-Path $PSScriptRoot "..\launcher\assets")) {
    Copy-Item (Join-Path $PSScriptRoot "..\launcher\assets") $target -Recurse -Force
}
Write-Host "Installed the launcher into $target"
