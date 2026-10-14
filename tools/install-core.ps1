# Installs Stilwater's DFEngine.dll (core) into the Saints Row 2 folder.
# The DFEngine.dll it replaces is backed up once to <game>\_backup_juiced\ first.
param(
    [string] $GameFolder = "E:\SteamLibrary\steamapps\common\Saints Row 2",
    [string] $Dll = (Join-Path $PSScriptRoot "..\dist\DFEngine.dll")
)
$ErrorActionPreference = "Stop"

if (Get-Process -Name SR2_pc, SR2MP -ErrorAction SilentlyContinue) { throw "Close Saints Row 2 first." }
if (-not (Test-Path $Dll)) { throw "$Dll not found. Run build.ps1 first." }

$target = Join-Path $GameFolder "DFEngine.dll"
$backup = Join-Path $GameFolder "_backup_juiced"
if (-not (Test-Path (Join-Path $backup "DFEngine.dll"))) {
    New-Item -ItemType Directory -Force $backup | Out-Null
    Copy-Item $target $backup
    Write-Host "Backed up the current DFEngine.dll to $backup"
}
Copy-Item $Dll $target -Force
Write-Host "Installed Stilwater core into $GameFolder"
