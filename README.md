# Stilwater

Made by [holdonquietly.com](https://holdonquietly.com).

A custom client for **Saints Row 2** on PC: our own launcher, our own core patch, and a runtime that runs inside the game. The idea is the same as ReSkate's: keep the original game, and replace or extend it one system at a time.

The core is a fork of [Juiced Patch](https://github.com/kobraworksmodding/Saints-Row-2-Juiced-Patch) v9.2.0, by the Juiced Team.

## Status

- **Core:** builds and shows Stilwater branding on the main menu, in the first-boot welcome and in in-game messages. Juiced's own update prompts are disabled.
- **Launcher:** finds Saints Row 2 in your Steam libraries, checks the exe build, 4 GB memory patch (LAA), core and DXVK, and starts the game with the runtime loaded. Its pages: **Play**; **Friends** (your online account, which the game's co-op uses too, friends, friend requests and co-op invites); **Mods** (switch loose mods on and off, and a mods code co-op partners compare); **Settings** (including making Steam's Play button open the launcher).
- **Co-op:** online co-op runs on **Stilwater Online**, our own replacement for GameSpy (`server/`): accounts, friends, invites, the game list and NAT negotiation. The core sends the game's GameSpy traffic there, or to OpenSpy if `[Stilwater] OnlineServer` is `openspy`, and forwards the game's ports through UPnP while it runs.
- **Runtime:** checks the game build, the core, and the window and display settings, and logs what it finds.
- **Controls tool:** applies GTA Online-style controls for controller and keyboard/mouse.

## Components

| Folder | What it is |
|---|---|
| `core/` | `DFEngine.dll`, the core patch: a fork of Juiced Patch v9.2.0. See `core/UPSTREAM.md` for what changed. |
| `launcher/` | `StilwaterLauncher.exe`, a C# / .NET 8 WinForms launcher. |
| `runtime/` | `stilwater.dll`, the 32-bit C++ runtime that runs inside `SR2_pc.exe`, and `stilwater-loader.exe`, which starts the game with the runtime loaded. |
| `server/` | Stilwater Online: the GameSpy services SR2's co-op uses (accounts and friends, player search, host registration, the encrypted game list, NAT negotiation), in Python 3 with no dependencies. `deploy.sh` installs it as a systemd service; `test_online.py` checks a running server end to end. |
| `tools/controls/` | `gta_layout.py`, which applies GTA Online-style controls (controller and keyboard/mouse) to the game's `input.bin`. |
| `installer/` | `install.bat` and `install.ps1`, which players run from a release zip: they set up Juiced Patch, the exe, DirectX, .NET, DXVK and Steam's Play button, then install the core, launcher and mods. The launcher's Update button runs the same installer. |
| `tools/release.ps1` | Builds, packages `release\Stilwater-<version>.zip`, commits and pushes, and publishes the GitHub release (the launcher's staff Upload button runs it). |
| `tools/install-core.ps1` | Installs the built core into the game folder, backing up the DLL it replaces. |
| `tools/install-launcher.ps1` | Installs the launcher and runtime into `<game>\Stilwater\`, where Steam's launch options point. |
| `docs/` | Reverse-engineering notes: addresses, file formats, findings. |

## Installing (players)

Download the newest release zip from [Releases](https://github.com/dwindles/stilwater/releases), extract it and run `install.bat`. Saints Row 2 from Steam is all it needs: it downloads Juiced Patch v9.2.0 from its GitHub release (checked against a known hash), turns Steam's encrypted `SR2_pc.exe` into the unencrypted build with Juiced's patch and sets the 4 GB flag, installs the game's DirectX 9 and the .NET 8 Desktop Runtime when they're missing, adds DXVK on PCs with Vulkan, and sets Steam's Play button to open the launcher. After that, the launcher's Update button installs new releases.

## Publishing a release

Set `RepoFolder` under `[Stilwater]` in `juiced.ini` to this checkout and the launcher shows an Upload button, which runs `tools\release.ps1` (`-NoPublish` only builds and packages). It needs git and the GitHub CLI signed in as the repo's owner, and refuses to publish if anything that looks like a webhook URL, token or private key is in the tree or its history.

## Requirements (building)

- Saints Row 2 on Steam (or GOG).
- The Juiced Patch v9.2.0 release, installed once (`installer\install.ps1` does it). It provides the `mods/` assets the core loads, and on Steam its patch replaces the DRM-encrypted `SR2_pc.exe` with an unencrypted build.
- Visual Studio 2022 Build Tools with the C++ x86 toolset, CMake 3.20+ and the .NET 8 SDK, to build.

## Build and run

```powershell
.\build.ps1                  # core, runtime and launcher into .\dist
.\tools\install-core.ps1     # with the game closed
.\tools\install-launcher.ps1 # then: launcher Settings → Steam → Set up
.\dist\StilwaterLauncher.exe
```

`StilwaterLauncher.exe --play` launches without opening the window and writes the result to `dist\logs\launcher.log`. The runtime writes to `dist\logs\runtime.log`.

To switch to GTA Online controls, close the game and run `python tools\controls\gta_layout.py`. It sets both the controller and the keyboard/mouse bindings (right mouse aims) and keeps your original file as `input.bin.bak`.

## Stilwater Online

```bash
server/deploy.sh root@<server> -p <ssh port> -i <key>   # installs or updates the service
python server/test_online.py <server>                   # end-to-end check
```

It listens on TCP 29900 (accounts and friends), TCP 29901 (search), UDP 27900 (availability and host registration), TCP 28910 (game list) and UDP 27901 (NAT negotiation); open those in the server's firewall. Accounts live in `/var/lib/stilwater-online/accounts.db`. Passwords are stored as MD5, because GameSpy's login proof is built from it, so use a password you don't use anywhere else. The launcher and the core both read the address from `[Stilwater] OnlineServer` in `juiced.ini` (Settings → Co-op → Online server).

To log what happens (new accounts, sign-ins, friendships, invites, hosted games) to Discord, put `STILWATER_DISCORD_WEBHOOK=<webhook URL>` in `/etc/stilwater-online/discord.env` on the server and restart it (`systemctl restart stilwater-online`).

## How loading works

1. `stilwater-loader.exe` starts `SR2_pc.exe` suspended, with the game folder as its working directory.
2. It calls `LoadLibraryW` on a remote thread to load `stilwater.dll`.
3. It resumes the game.

The loader must be 32-bit so that `LoadLibraryW` resolves to the same address it has inside the game. The runtime never does real work in `DllMain`; everything runs on its own thread.

## Roadmap

- **Runtime:** bring SR2 Reloaded's extended render, tree-fade and shadow distances to single-player.
- **Runtime:** add Stilwater options to the in-game menu through JuicedAPI.
- **Launcher:** repair the exe patch after a Steam file verify, without an admin prompt.
- **Launcher:** install and update the core, add a Mods folder, add a settings screen, and offer a controller layout picker.
- **Stilwater Online:** serve the HTTP services (login certificates, Sake storage, competition) if the game turns out to need them, and a domain name instead of the bare address.

## Credits

The core is Juiced Patch by the Juiced Team (Kobraworks Modding Group: Soaa, Tervel, Clippy, Scanti and contributors). Juiced builds on scanti's Monkey Patch.

## License

`core/` is released under the MIT License, `Copyright (c) 2025 Kobraworks Modding Group`. See `core/license.txt`. Upstream moved to GPL-3.0 after v9.2.0, so merging newer upstream code would bring in GPL-3.0 terms.

## Legal

You need your own copy of Saints Row 2. This repository contains no game code or assets. The addresses and notes in `docs/` are documented for interoperability.
