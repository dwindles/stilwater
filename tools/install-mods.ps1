# Copies every built Stilwater mod folder (mods\*\out\STILWATER - *) into the game's mods folder and
# lists it in loose.txt (unless loose.txt has it commented out with "#", which keeps it switched off).
# A folder being replaced is moved to _backup_juiced\old mods first.
# Refuses while the game is running, since it reads these files on demand.
param([string]$Game = "E:\SteamLibrary\steamapps\common\Saints Row 2")
$ErrorActionPreference = "Stop"

if (Get-Process -Name SR2_pc, SR2MP -ErrorAction SilentlyContinue) { throw "Close Saints Row 2 first." }

$root = Split-Path $PSScriptRoot
$loose = Join-Path $Game "loose.txt"
$backup = Join-Path $Game "_backup_juiced\old mods"
$stamp = Get-Date -Format yyyyMMdd-HHmmss
$lines = [Collections.Generic.List[string]]::new()
[IO.File]::ReadAllLines($loose) | Where-Object { $_ -ne "" } | ForEach-Object { $lines.Add($_) }

$builtFolders = Get-ChildItem (Join-Path $root "mods\*\out\*") -Directory | Where-Object Name -like "STILWATER - *"
if (-not $builtFolders) { throw "No built mods under $root\mods\*\out." }
foreach ($built in $builtFolders) {
    $target = Join-Path $Game "mods\$($built.Name)"
    if (Test-Path $target) {
        New-Item -ItemType Directory -Force $backup | Out-Null
        Move-Item $target (Join-Path $backup "$($built.Name) $stamp")
    }
    Copy-Item $built.FullName $target -Recurse
    $entry = "mods/$($built.Name)"
    # A "#mods/..." line keeps a mod switched off (two mods replacing the same game car can't both
    # load); it stays off until the line is uncommented.
    if ($lines -contains "#$entry") {
        Write-Host "Installed $($built.Name) (switched off in loose.txt)"
        continue
    }
    if (-not ($lines -contains $entry)) { $lines.Add($entry) }
    Write-Host "Installed $($built.Name)"
}

# CRLF with a trailing newline, as the loader and other tools expect.
[IO.File]::WriteAllText($loose, ($lines -join "`r`n") + "`r`n", [Text.Encoding]::ASCII)
