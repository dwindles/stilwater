# Stilwater

Made by [holdonquietly.com](https://holdonquietly.com).

A custom client for **Saints Row 2** on PC: our own launcher, our own core patch, and a runtime that runs inside the game. The idea is the same as ReSkate's: keep the original game, and replace or extend it one system at a time.

The core is a fork of [Juiced Patch](https://github.com/kobraworksmodding/Saints-Row-2-Juiced-Patch) v9.2.0, by the Juiced Team.

## Status

- **Core:** builds and shows Stilwater branding on the main menu, in the first-boot welcome and in in-game messages. Juiced's own update prompts are disabled.
- **Launcher:** finds Saints Row 2 in your Steam libraries, checks the exe build, 4 GB memory patch (LAA), core and DXVK, and starts the game with the runtime loaded.
- **Runtime:** checks the game build, the core, and the window and display settings, and logs what it finds.
- **Controls tool:** applies GTA Online-style controls for controller and keyboard/mouse.

## Components

| Folder | What it is |
|---|---|
| `core/` | `DFEngine.dll`, the core patch: a fork of Juiced Patch v9.2.0. See `core/UPSTREAM.md` for what changed. |
| `launcher/` | `StilwaterLauncher.exe`, a C# / .NET 8 WinForms launcher. |
| `runtime/` | `stilwater.dll`, the 32-bit C++ runtime that runs inside `SR2_pc.exe`, and `stilwater-loader.exe`, which starts the game with the runtime loaded. |
| `tools/controls/` | `gta_layout.py`, which applies GTA Online-style controls (controller and keyboard/mouse) to the game's `input.bin`. |
| `tools/install-core.ps1` | Installs the built core into the game folder, backing up the DLL it replaces. |
| `docs/` | Reverse-engineering notes: addresses, file formats, findings. |

## Requirements

- Saints Row 2 on Steam (or GOG).
- The Juiced Patch v9.2.0 release, installed once. It provides the `mods/` assets the core loads, and on Steam it replaces the DRM-encrypted `SR2_pc.exe` with an unencrypted build.
- Visual Studio 2022 Build Tools with the C++ x86 toolset, CMake 3.20+ and the .NET 8 SDK, to build.

## Build and run

```powershell
.\build.ps1                  # core, runtime and launcher into .\dist
.\tools\install-core.ps1     # with the game closed
.\dist\StilwaterLauncher.exe
```

`StilwaterLauncher.exe --play` launches without opening the window and writes the result to `dist\logs\launcher.log`. The runtime writes to `dist\logs\runtime.log`.

To switch to GTA Online controls, close the game and run `python tools\controls\gta_layout.py`. It sets both the controller and the keyboard/mouse bindings (right mouse aims) and keeps your original file as `input.bin.bak`.

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
- **Later:** multiplayer and server work.

## Credits

The core is Juiced Patch by the Juiced Team (Kobraworks Modding Group: Soaa, Tervel, Clippy, Scanti and contributors). Juiced builds on scanti's Monkey Patch.

## License

`core/` is released under the MIT License, `Copyright (c) 2025 Kobraworks Modding Group`. See `core/license.txt`. Upstream moved to GPL-3.0 after v9.2.0, so merging newer upstream code would bring in GPL-3.0 terms.

## Legal

You need your own copy of Saints Row 2. This repository contains no game code or assets. The addresses and notes in `docs/` are documented for interoperability.
