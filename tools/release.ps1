# Publishes a Stilwater release (the launcher's staff Upload button runs this): builds everything,
# packages release\Stilwater-<version>.zip (installer\, the launcher and runtime, the core and the
# built mods), commits and pushes the repo, and creates the GitHub release the launcher's Update
# button installs. The first run creates the GitHub repo.
#   tools\release.ps1 [-Version 0.2.1] [-Notes "What changed"] [-NoPublish]
# -NoPublish only builds and packages. Needs git and the GitHub CLI (gh), signed in as the owner.
param(
    [string] $Version = "",
    [string] $Notes = "",
    [switch] $NoPublish
)
$ErrorActionPreference = "Stop"
$Repository = "dwindles/stilwater"
$root = Split-Path $PSScriptRoot
Set-Location $root

function Step([string] $text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Magenta }
function Run([string] $what) { if ($LASTEXITCODE) { throw "$what failed (exit code $LASTEXITCODE)" } }

# Git for Windows doesn't always put itself on PATH (Git Bash finds it anyway), so look where it and
# the other tools usually live before giving up.
$toolFolders = @{
    git = @("$env:ProgramFiles\Git\cmd", "${env:ProgramFiles(x86)}\Git\cmd", "$env:LOCALAPPDATA\Programs\Git\cmd") +
          @(Get-ChildItem "$env:LOCALAPPDATA\GitHubDesktop\app-*\resources\app\git\cmd" -Directory -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | ForEach-Object FullName)
    gh = @("$env:ProgramFiles\GitHub CLI", "$env:LOCALAPPDATA\Programs\GitHub CLI")
    dotnet = @("$env:ProgramFiles\dotnet")
    cmake = @("$env:ProgramFiles\CMake\bin")
}
foreach ($tool in $toolFolders.Keys) {
    if (Get-Command $tool -ErrorAction SilentlyContinue) { continue }
    $folder = $toolFolders[$tool] | Where-Object { $_ -and (Test-Path (Join-Path $_ "$tool.exe")) } | Select-Object -First 1
    if (-not $folder) { throw "$tool wasn't found. Install it (or add it to PATH) and try again." }
    $env:Path = "$folder;$env:Path"
}

# The next version: one past the newest release tag, or the launcher's own for the first release.
if (-not $Version) {
    $last = git tag --list "v*" --sort=-v:refname | Select-Object -First 1
    if ($last) {
        $v = [version]$last.TrimStart("v")
        $Version = "$($v.Major).$($v.Minor).$($v.Build + 1)"
    } else {
        $Version = ([xml](Get-Content -Raw "$root\launcher\Stilwater.Launcher.csproj")).Project.PropertyGroup.Version | Where-Object { $_ } | Select-Object -First 1
    }
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like 1.2.3 (got '$Version')." }
if (-not $NoPublish -and (git tag --list "v$Version")) { throw "v$Version already exists. Pick a newer version." }
Write-Host "Stilwater v$Version" -ForegroundColor Magenta

Step "Building"
& "$root\build.ps1" -Version $Version

Step "Packaging"
$stage = Join-Path $root "release\Stilwater-$Version"
$zip = Join-Path $root "release\Stilwater-$Version.zip"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force "$stage\Stilwater", "$stage\mods" | Out-Null
Copy-Item "$root\installer\*" $stage
Copy-Item "$root\dist\DFEngine.dll" $stage
Get-ChildItem "$root\dist" -File | Where-Object { $_.Name -ne "DFEngine.dll" -and $_.Extension -ne ".pdb" } |
    Copy-Item -Destination "$stage\Stilwater"
if (Test-Path "$root\launcher\assets") { Copy-Item "$root\launcher\assets" "$stage\Stilwater" -Recurse }
# DXVK (32-bit d3d9.dll and dxgi.dll), which the installer adds on PCs with Vulkan.
$dxvk = if ($env:STILWATER_DXVK) { $env:STILWATER_DXVK } else { "D:\tools\dxvk-3.1.1\dxvk-3.1.1\x32" }
if (-not (Test-Path "$dxvk\d3d9.dll")) { throw "DXVK not found in $dxvk (set STILWATER_DXVK to a DXVK x32 folder)." }
New-Item -ItemType Directory -Force "$stage\dxvk" | Out-Null
Copy-Item "$dxvk\d3d9.dll", "$dxvk\dxgi.dll" "$stage\dxvk"
Set-Content "$stage\dxvk\README.txt" "DXVK $((Split-Path (Split-Path $dxvk) -Leaf) -replace 'dxvk-', '') by Philip Rebohle and contributors (zlib license): https://github.com/doitsujin/dxvk" -Encoding ASCII
$mods = Get-ChildItem "$root\mods\*\out\*" -Directory | Where-Object Name -like "STILWATER - *"
$mods | Copy-Item -Destination "$stage\mods" -Recurse
# Mods switched off in this machine's loose.txt start switched off for players too (two car mods
# that replace the same car can't both load).
$steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue).SteamPath
$libraries = @($steam)
if ($steam -and (Test-Path "$steam\steamapps\libraryfolders.vdf")) {
    $libraries += [regex]::Matches((Get-Content -Raw "$steam\steamapps\libraryfolders.vdf"), '"path"\s+"([^"]+)"') |
        ForEach-Object { $_.Groups[1].Value.Replace("\\", "\") }
}
$loose = $libraries | Where-Object { $_ } | ForEach-Object { Join-Path $_ "steamapps\common\Saints Row 2\loose.txt" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($loose) {
    Get-Content $loose | Where-Object { $_ -like "#mods/STILWATER - *" } | ForEach-Object { $_.Substring(1) } |
        Set-Content "$stage\mods-off.txt" -Encoding ASCII
}
Set-Content "$stage\version.txt" $Version -Encoding ASCII
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Write-Host "$zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB, $($mods.Count) mods)"
if ($NoPublish) { return }

Step "Checking for secrets"
# From here on git and gh do the work. Their progress and warnings go to stderr, which Windows
# PowerShell can turn into errors under "Stop", so failures are caught by exit code (Run) instead.
$ErrorActionPreference = "Continue"
git add -A; Run "git add"
# Webhook URLs, bot and GitHub tokens, private keys: none of them belong in a public repo, in the
# files being committed or anywhere in the history being pushed.
$secret = 'discord(app)?\.com/api/webhooks/|BEGIN [A-Z ]*PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{30,}|[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}'
$leaks = @(git grep --cached -I -l -E $secret) + @(git log --all --format="commit %h" -G $secret)
if ($leaks) {
    git reset -q
    throw "These look like they contain a secret, so nothing was published: $($leaks -join ', ')"
}

Step "Committing and pushing"
if (@(git remote) -notcontains "origin") {
    gh repo create $Repository --public --description "Stilwater: a Saints Row 2 client by holdonquietly.com" --source $root --remote origin
    Run "gh repo create"
}
git diff --cached --quiet
if ($LASTEXITCODE) {
    $message = if ($Notes) { "Release v$Version`n`n$Notes" } else { "Release v$Version" }
    git commit -q -m $message; Run "git commit"
}
$branch = git rev-parse --abbrev-ref HEAD
# main follows the newest release, so the repo's front page matches what players get. It goes
# first: on a new repo the first branch pushed becomes the default.
if ($branch -ne "main") {
    git merge-base --is-ancestor main HEAD
    if (-not $LASTEXITCODE) { git push origin HEAD:main; Run "git push main" }
    else { Write-Host "main has commits this branch doesn't; left it alone." -ForegroundColor Yellow }
}
git push -u origin $branch; Run "git push"

Step "Publishing the release"
$body = if ($Notes) { $Notes } else { "Stilwater v$Version." }
$body += "`n`nInstall: extract the zip and run install.bat. It needs Saints Row 2 from Steam and sets up everything else (Juiced Patch, DirectX, .NET, DXVK). Already installed? Press Update in the launcher."
gh release create "v$Version" $zip --repo $Repository --title "Stilwater v$Version" --notes $body --target $branch
Run "gh release create"
Write-Host ""
Write-Host "Published Stilwater v${Version}: https://github.com/$Repository/releases/tag/v$Version" -ForegroundColor Green
