# Stilwater

A custom client for **Saints Row 2** on PC: our own launcher plus a runtime that runs inside the game, alongside [Juiced Patch](https://github.com/kobraworksmodding/Saints-Row-2-Juiced-Patch). The idea is the same as ReSkate's: keep the original game, and replace or extend it one system at a time.

## Status

**Milestone 0: the pipeline works.**

- The launcher finds Saints Row 2 in your Steam libraries and checks its setup: exe build, 4 GB memory patch (LAA), Juiced Patch and DXVK.
- **Play** starts the game with the Stilwater runtime loaded.
- The runtime checks the game build, Juiced, and the window and display settings, and logs what it finds.

There are no gameplay changes yet.

## Components

| Folder | What it is |
|---|---|
| `launcher/` | `StilwaterLauncher.exe`, a C# / .NET 8 WinForms launcher. |
| `runtime/` | `stilwater.dll`, the 32-bit C++ runtime that runs inside `SR2_pc.exe`, and `stilwater-loader.exe`, which starts the game with the runtime loaded. |
| `docs/` | Reverse-engineering notes: addresses, file formats, findings. |

## Requirements

- Saints Row 2 on Steam (or GOG).
- Juiced Patch 9.x. On Steam it replaces the DRM-encrypted `SR2_pc.exe` with an unencrypted build, which Stilwater needs.
- Visual Studio 2022 Build Tools with the C++ x86 toolset, CMake 3.20+ and the .NET 8 SDK, to build.

## Build and run

```powershell
.\build.ps1
.\dist\StilwaterLauncher.exe
```

`StilwaterLauncher.exe --play` launches without opening the window and writes the result to `dist\logs\launcher.log`. The runtime writes to `dist\logs\runtime.log`.

## How loading works

1. `stilwater-loader.exe` starts `SR2_pc.exe` suspended, with the game folder as its working directory.
2. It calls `LoadLibraryW` on a remote thread to load `stilwater.dll`.
3. It resumes the game.

The loader must be 32-bit so that `LoadLibraryW` resolves to the same address it has inside the game. The runtime never does real work in `DllMain`; everything runs on its own thread.

## Roadmap

- **Runtime:** bring SR2 Reloaded's extended render, tree-fade and shadow distances to single-player.
- **Runtime:** add Stilwater options to the in-game menu through JuicedAPI.
- **Launcher:** repair the exe patch after a Steam file verify, without an admin prompt.
- **Launcher:** install and update Juiced, add a Mods folder, and add a settings screen.
- **Later:** multiplayer and server work.

## Legal

You need your own copy of Saints Row 2. This repository contains no game code or assets. The addresses and notes in `docs/` are documented for interoperability.
