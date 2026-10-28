# Installs (or updates) Stilwater into a Saints Row 2 install, with everything it needs:
#   - Juiced Patch v9.2.0 (downloaded from its GitHub release and checked against a known hash) when
#     it isn't installed: the JUICED mods, SDL3, the Discord SDK and Juiced's exe patch,
#   - Steam's DRM-encrypted SR2_pc.exe turned into the unencrypted build with Juiced's patch, and
#     the 4 GB (large address aware) flag set,
#   - the game's DirectX 9 redistributable when its DLLs are missing, and the .NET 8 Desktop
#     Runtime the launcher runs on (from Microsoft, signature checked) when it isn't installed,
#   - the Stilwater core (DFEngine.dll), launcher (<game>\Stilwater\) and mods (<game>\mods\),
#   - DXVK on PCs with Vulkan, and Steam's Play button opening the launcher.
# Run it through install.bat. The launcher's Update button runs it too, with -WaitFor <its PID>.
#   install.ps1 [-Game <folder>] [-JuicedZip <SR2_JUICED.zip>] [-WaitFor <pid>] [-NoSteam] [-NoShortcut] [-NoLaunch]
param(
    [string] $Game = "",
    [string] $Source = $PSScriptRoot,
    [string] $JuicedZip = "",
    [int] $WaitFor = 0,
    [switch] $NoSteam,
    [switch] $NoShortcut,
    [switch] $NoLaunch
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"        # Invoke-WebRequest's progress bar slows downloads to a crawl
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$JuicedUrl = "https://github.com/kobraworksmodding/Saints-Row-2-Juiced-Patch/releases/download/v9.2.0/SR2_JUICED.zip"
$JuicedSha256 = "F3C77AD368E808F142C1008B2D4A0DEA9FECC1F7E943542A5178F15BFE287B16"
$DotNetUrl = "https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe"      # the newest 8.0.x
# Settings a fresh juiced.ini starts with: no debug console, clearer lighting, sharper smooth
# shadows, GTA-style hold to aim.
$JuicedDefaults = @{
    "Logger" = @{ "Console" = "0" }
    "Graphics" = @{ "VanillaFXPlus" = "1"; "ShadowMapRes" = "4096"; "ShadowFiltering" = "1" }
    "Input" = @{ "HoldFineAim" = "1" }
}
$DirectXDlls = "d3dx9_39.dll", "x3daudio1_4.dll", "xinput1_3.dll"   # what SR2_pc.exe imports

function Say([string] $text, [string] $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Fail([string] $text) { Say ""; Say $text "Red"; exit 1 }

# Saints Row 2 (Steam app 9480) in any Steam library.
function Find-Game {
    $steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue).SteamPath
    if (-not $steam) { return $null }
    $libraries = @($steam)
    $vdf = Join-Path $steam "steamapps\libraryfolders.vdf"
    if (Test-Path $vdf) {
        foreach ($m in [regex]::Matches((Get-Content -Raw $vdf), '"path"\s+"([^"]+)"')) { $libraries += $m.Groups[1].Value.Replace("\\", "\") }
    }
    foreach ($library in $libraries | Select-Object -Unique) {
        $manifest = Join-Path $library "steamapps\appmanifest_9480.acf"
        if (-not (Test-Path $manifest)) { continue }
        $dir = [regex]::Match((Get-Content -Raw $manifest), '"installdir"\s+"([^"]+)"')
        $folder = Join-Path $library "steamapps\common\$($dir.Groups[1].Value)"
        if ($dir.Success -and (Test-Path (Join-Path $folder "SR2_pc.exe"))) { return (Resolve-Path $folder).Path }
    }
    return $null
}

function Test-Writable([string] $folder) {
    try { $probe = Join-Path $folder ".stilwater-write-test"; [IO.File]::WriteAllText($probe, ""); Remove-Item $probe; return $true }
    catch { return $false }
}

# PE header bits of the game exe: Steam's DRM adds a .bind section; the 4 GB flag is 0x20 in the
# file header's characteristics.
function Get-PeInfo([string] $path) {
    $bytes = [IO.File]::ReadAllBytes($path)
    $pe = [BitConverter]::ToInt32($bytes, 0x3C)
    $count = [BitConverter]::ToUInt16($bytes, $pe + 6)
    $at = $pe + 24 + [BitConverter]::ToUInt16($bytes, $pe + 20)
    $sections = 0..($count - 1) | ForEach-Object { [Text.Encoding]::ASCII.GetString($bytes, $at + 40 * $_, 8).TrimEnd([char]0) }
    [pscustomobject]@{ Bytes = $bytes; Flags = $pe + 22; Encrypted = $sections -contains ".bind"; LargeAddressAware = ($bytes[$pe + 22] -band 0x20) -ne 0 }
}

function Set-IniValues([string] $path, [hashtable] $values) {
    $lines = [Collections.Generic.List[string]]([IO.File]::ReadAllLines($path))
    foreach ($section in $values.Keys) {
        $start = $lines.IndexOf("[$section]")
        if ($start -lt 0) { continue }
        foreach ($key in $values[$section].Keys) {
            for ($i = $start + 1; $i -lt $lines.Count -and -not $lines[$i].StartsWith("["); $i++) {
                if ($lines[$i] -like "$key=*") { $lines[$i] = "$key=$($values[$section][$key])"; break }
            }
        }
    }
    [IO.File]::WriteAllText($path, ($lines -join "`r`n") + "`r`n")
}

$version = if (Test-Path (Join-Path $Source "version.txt")) { (Get-Content -Raw (Join-Path $Source "version.txt")).Trim() } else { "?" }
Say "Stilwater $version installer" "Magenta"
Say ""

if (-not (Test-Path (Join-Path $Source "DFEngine.dll"))) { Fail "This folder isn't a Stilwater release (DFEngine.dll is missing). Extract the whole zip first." }
if (-not $Game) { $Game = Find-Game }
if (-not $Game -or -not (Test-Path (Join-Path $Game "SR2_pc.exe"))) {
    Fail "Saints Row 2 wasn't found in your Steam libraries. Install it from Steam, or run: install.bat -Game ""<your Saints Row 2 folder>"""
}
Say "Saints Row 2: $Game"

# Program Files game folders and the DirectX setup need administrator rights: ask once, up front.
$system32 = Join-Path $env:windir "SysWOW64"
if (-not (Test-Path $system32)) { $system32 = Join-Path $env:windir "System32" }
$needsDirectX = @($DirectXDlls | Where-Object { -not (Test-Path (Join-Path $system32 $_)) }).Count -gt 0
$needsDotNet = -not (Get-ChildItem (Join-Path $env:ProgramFiles "dotnet\shared\Microsoft.WindowsDesktop.App") -Directory -Filter "8.*" -ErrorAction SilentlyContinue)
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin -and ($needsDirectX -or $needsDotNet -or -not (Test-Writable $Game))) {
    Say "Windows will ask for permission: the game folder, DirectX or .NET setup needs it."
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Game", "`"$Game`"", "-Source", "`"$Source`"")
    if ($JuicedZip) { $arguments += @("-JuicedZip", "`"$JuicedZip`"") }
    if ($WaitFor) { $arguments += @("-WaitFor", $WaitFor) }
    foreach ($flag in "NoSteam", "NoShortcut", "NoLaunch") { if ((Get-Variable $flag).Value) { $arguments += "-$flag" } }
    try { $elevated = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru }
    catch { Fail "Permission was refused, so nothing was installed." }
    exit $elevated.ExitCode
}

if ($WaitFor) {
    Say "Waiting for the launcher to close..."
    Wait-Process -Id $WaitFor -ErrorAction SilentlyContinue
}
while (Get-Process -Name SR2_pc, SR2MP -ErrorAction SilentlyContinue) {
    Say "Saints Row 2 is running. Close it to continue (checking again in 5 seconds)..." "Yellow"
    Start-Sleep -Seconds 5
}
while (Get-Process -Name StilwaterLauncher -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Game\*" }) {
    Say "The Stilwater launcher is open. Close it to continue (checking again in 5 seconds)..." "Yellow"
    Start-Sleep -Seconds 5
}

# The originals Stilwater replaces, kept once.
$backup = Join-Path $Game "_backup_pre_stilwater"
New-Item -ItemType Directory -Force $backup | Out-Null
function Backup([string] $name) {
    $file = Join-Path $Game $name
    if ((Test-Path $file) -and -not (Test-Path (Join-Path $backup $name))) { Copy-Item $file $backup }
}

# --- Juiced Patch
$hasJuiced = (Test-Path (Join-Path $Game "SDL3.dll")) -and (Test-Path (Join-Path $Game "patches\JuicedSteamXDel.vcdiff")) -and
             (Get-ChildItem (Join-Path $Game "mods") -Directory -Filter "JUICED - *" -ErrorAction SilentlyContinue)
if (-not $hasJuiced) {
    $setup = Join-Path $Game "_stilwater_setup"
    New-Item -ItemType Directory -Force $setup | Out-Null
    if (-not $JuicedZip) {
        $JuicedZip = Join-Path $setup "SR2_JUICED.zip"
        Say "Downloading Juiced Patch v9.2.0 (41 MB)..."
        try { Invoke-WebRequest $JuicedUrl -OutFile $JuicedZip -UseBasicParsing }
        catch { Fail "Couldn't download Juiced Patch ($($_.Exception.Message)). Check your internet connection and run install.bat again." }
    }
    if ((Get-FileHash $JuicedZip -Algorithm SHA256).Hash -ne $JuicedSha256) { Fail "$JuicedZip isn't the Juiced Patch v9.2.0 release (its hash doesn't match), so it wasn't used." }
    Say "Installing Juiced Patch v9.2.0..."
    $juiced = Join-Path $setup "juiced"
    Expand-Archive $JuicedZip $juiced -Force
    Backup "discord_game_sdk.dll"
    New-Item -ItemType Directory -Force (Join-Path $Game "mods"), (Join-Path $Game "patches"), (Join-Path $Game "Juiced") | Out-Null
    Get-ChildItem (Join-Path $juiced "Mods") -Directory | Copy-Item -Destination (Join-Path $Game "mods") -Recurse -Force
    Copy-Item (Join-Path $juiced "patches\*") (Join-Path $Game "patches") -Force
    Copy-Item (Join-Path $juiced "Juiced\*") (Join-Path $Game "Juiced") -Recurse -Force
    foreach ($file in "SDL3.dll", "discord_game_sdk.dll", "gamecontrollerdb.txt", "JuicedSteamXDel.bat") {
        Copy-Item (Join-Path $juiced $file) $Game -Force
    }
    # The game folder has its own license.txt and readme; Juiced's (GPL-3.0) go in the Juiced folder.
    Copy-Item (Join-Path $juiced "license.txt"), (Join-Path $juiced "readme.txt") (Join-Path $Game "Juiced") -Force
    if (-not (Test-Path (Join-Path $Game "juiced.ini"))) {
        Copy-Item (Join-Path $juiced "juiced.ini") $Game
        Set-IniValues (Join-Path $Game "juiced.ini") $JuicedDefaults
    }
    # Juiced's mods go first in loose.txt (the first copy of a file wins).
    $loose = Join-Path $Game "loose.txt"
    $existing = if (Test-Path $loose) { @([IO.File]::ReadAllLines($loose) | Where-Object { $_ -and $_ -ne "mods" }) } else { @() }
    $juicedLines = @([IO.File]::ReadAllLines((Join-Path $juiced "loose.txt")) | Where-Object { $_ })
    $merged = $juicedLines + @($existing | Where-Object { $juicedLines -notcontains $_ })
    [IO.File]::WriteAllText($loose, ($merged -join "`r`n") + "`r`n", [Text.Encoding]::ASCII)
    Remove-Item $setup -Recurse -Force -ErrorAction SilentlyContinue
    Say "Installed Juiced Patch"
}

# --- The game exe: unencrypted (Juiced's patch for Steam's build) and 4 GB aware
$exe = Join-Path $Game "SR2_pc.exe"
$info = Get-PeInfo $exe
if ($info.Encrypted) {
    Say "Patching SR2_pc.exe (Steam's encrypted build) with Juiced's patch..."
    Backup "SR2_pc.exe"
    $unpatched = Join-Path $Game "sr2_pc_unpatched.exe"
    if (Test-Path $unpatched) { Remove-Item $unpatched -Force }
    Move-Item $exe $unpatched
    & (Join-Path $Game "patches\xdelta3.exe") -d -s $unpatched (Join-Path $Game "patches\JuicedSteamXDel.vcdiff") $exe
    if ($LASTEXITCODE -or -not (Test-Path $exe)) {
        if (Test-Path $exe) { Remove-Item $exe -Force }
        Move-Item $unpatched $exe
        Fail "Juiced's patch doesn't fit this SR2_pc.exe. In Steam: Saints Row 2 > Properties > Installed Files > Verify integrity, then run install.bat again."
    }
    $info = Get-PeInfo $exe
}
if (-not $info.LargeAddressAware) {
    $info.Bytes[$info.Flags] = $info.Bytes[$info.Flags] -bor 0x20
    [IO.File]::WriteAllBytes($exe, $info.Bytes)
    Say "Let SR2_pc.exe use 4 GB of memory"
}

# --- DirectX 9 (Steam runs this on the first Play; the launcher can start the game before that)
if ($needsDirectX -and (Test-Path (Join-Path $Game "DirectX\DXSETUP.exe"))) {
    Say "Installing DirectX 9 for Saints Row 2..."
    Start-Process (Join-Path $Game "DirectX\DXSETUP.exe") -ArgumentList "/silent" -Wait
}

# --- .NET 8 Desktop Runtime for the launcher
if ($needsDotNet) {
    Say "Installing the .NET 8 Desktop Runtime from Microsoft (about 58 MB)..."
    $runtime = Join-Path $Game "_stilwater_setup\windowsdesktop-runtime-8-win-x64.exe"
    New-Item -ItemType Directory -Force (Split-Path $runtime) | Out-Null
    try { Invoke-WebRequest $DotNetUrl -OutFile $runtime -UseBasicParsing }
    catch { Fail "Couldn't download the .NET 8 Desktop Runtime ($($_.Exception.Message)). Check your internet connection and run install.bat again." }
    $signature = Get-AuthenticodeSignature $runtime
    if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notlike "*O=Microsoft Corporation*") {
        Fail "The .NET download isn't signed by Microsoft, so it wasn't run."
    }
    Start-Process $runtime -ArgumentList "/install", "/quiet", "/norestart" -Wait
    Remove-Item (Split-Path $runtime) -Recurse -Force -ErrorAction SilentlyContinue
    Say "Installed the .NET 8 Desktop Runtime"
}

# --- Stilwater core
Backup "DFEngine.dll"
Copy-Item (Join-Path $Source "DFEngine.dll") (Join-Path $Game "DFEngine.dll") -Force
Say "Installed the Stilwater core"

# --- Launcher and runtime (settings and logs stay; launcher files an older version had go)
$launcher = Join-Path $Game "Stilwater"
New-Item -ItemType Directory -Force $launcher | Out-Null
$shipped = Get-ChildItem (Join-Path $Source "Stilwater") -Name
Get-ChildItem $launcher -File -Filter "StilwaterLauncher.*" | Where-Object { $shipped -notcontains $_.Name } | Remove-Item -Force
Copy-Item (Join-Path $Source "Stilwater\*") $launcher -Recurse -Force
Set-Content (Join-Path $launcher "version.txt") $version -Encoding ASCII
Say "Installed the launcher into $launcher"

# --- Mods: each folder is replaced whole. loose.txt keeps its order, and a mod switched off there
# ("#mods/...") stays off. New mods listed in mods-off.txt arrive switched off.
$loose = Join-Path $Game "loose.txt"
$lines = [Collections.Generic.List[string]]::new()
if (Test-Path $loose) { [IO.File]::ReadAllLines($loose) | Where-Object { $_ -ne "" } | ForEach-Object { $lines.Add($_) } }
if ($lines.Count -eq 0) { $lines.Add("mods") }
$off = if (Test-Path (Join-Path $Source "mods-off.txt")) { Get-Content (Join-Path $Source "mods-off.txt") } else { @() }
foreach ($mod in Get-ChildItem (Join-Path $Source "mods") -Directory) {
    $target = Join-Path $Game "mods\$($mod.Name)"
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Copy-Item $mod.FullName $target -Recurse
    $entry = "mods/$($mod.Name)"
    if (-not ($lines -contains $entry) -and -not ($lines -contains "#$entry")) {
        $lines.Add($(if ($off -contains $entry) { "#$entry" } else { $entry }))
    }
}
[IO.File]::WriteAllText($loose, ($lines -join "`r`n") + "`r`n", [Text.Encoding]::ASCII)
Say "Installed $((Get-ChildItem (Join-Path $Source "mods") -Directory).Count) Stilwater mods"

# --- DXVK (Direct3D 9 on Vulkan) when the PC has 32-bit Vulkan. A d3d9.dll or dxgi.dll from
# something else (ReShade, ENB) is left alone.
if ((Test-Path (Join-Path $Source "dxvk\d3d9.dll")) -and (Test-Path (Join-Path $system32 "vulkan-1.dll"))) {
    $installed = 0
    foreach ($dll in "d3d9.dll", "dxgi.dll") {
        $target = Join-Path $Game $dll
        if ((Test-Path $target) -and (Get-Item $target).VersionInfo.ProductName -ne "DXVK") {
            Say "Kept your $dll (it isn't DXVK)." "Yellow"
            continue
        }
        Copy-Item (Join-Path $Source "dxvk\$dll") $target -Force
        $installed++
    }
    if ($installed) { Say "Installed DXVK" }
}

# --- Desktop shortcut
$launcherExe = Join-Path $launcher "StilwaterLauncher.exe"
$shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Stilwater.lnk"
if (-not $NoShortcut -and -not (Test-Path $shortcut)) {
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    $link.TargetPath = $launcherExe
    $link.WorkingDirectory = $launcher
    $link.Save()
    Say "Added a Stilwater shortcut to your desktop"
}

# Programs started from here shouldn't inherit administrator rights: explorer starts them as you.
function Start-AsUser([string] $path) { if ($admin) { Start-Process explorer.exe "`"$path`"" } else { Start-Process $path -WorkingDirectory (Split-Path $path) } }

# --- Steam's Play button opens the launcher (Steam rewrites its settings on exit, so it must be closed)
$steamPath = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue).SteamPath
if (-not $NoSteam -and -not $WaitFor -and $steamPath) {
    $restartSteam = $false
    if (Get-Process steam -ErrorAction SilentlyContinue) {
        Say ""
        $answer = Read-Host "Steam's Play button can open Stilwater. That needs Steam closed for a moment; close and reopen it now? (Y/n)"
        if ($answer -notmatch '^[nN]') {
            Start-Process (Join-Path $steamPath "steam.exe") -ArgumentList "-shutdown"
            $deadline = (Get-Date).AddSeconds(60)
            while ((Get-Process steam -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
            $restartSteam = $true
        }
    }
    if (-not (Get-Process steam -ErrorAction SilentlyContinue)) {
        $result = (Start-Process $launcherExe -ArgumentList "--setup-steam" -Wait -PassThru).ExitCode
        if ($result -gt 0) { Say "Steam's Play button now opens Stilwater" }
        else { Say "Couldn't set Steam's Play button. In the launcher: Settings > Steam > Set up." "Yellow" }
    } else {
        Say "Tip: in the launcher, Settings > Steam > Set up makes Steam's Play button open Stilwater."
    }
    if ($restartSteam) { Start-AsUser (Join-Path $steamPath "steam.exe") }
}

Say ""
Say "Stilwater $version is installed." "Green"
if (-not $NoLaunch) { Start-AsUser $launcherExe }
