# Upstream

`core/` is a fork of [Saints Row 2 Juiced Patch](https://github.com/kobraworksmodding/Saints-Row-2-Juiced-Patch) by the Juiced Team (Kobraworks: Soaa, Tervel, Clippy, Scanti and contributors).

## License

- **This fork:** `v9.2.0` is released under the MIT License, `Copyright (c) 2025 Kobraworks Modding Group`. The full notice is in `license.txt` and must stay with this code.
- **Later upstream code:** upstream relicensed to GPL-3.0 on 2026-10-11, after this base. Merging upstream commits from that point on brings in GPL-3.0 terms.

- **Base:** tag `v9.2.0`, commit `f244988d6b9c7d8ada47d033ab2261d6c332584f`.
- **Submodules:** `external/spdlog` and `external/SDL_GameControllerDB` are vendored at the commits pinned by that tag.
- **Not included:** the `Mods/` asset folder and `ship/` installer files. Those come from the official v9.2.0 release.

## Stilwater changes

| File | Change |
|---|---|
| `Monkey Patch/UtilsGlobal.h` | Added `stilwaterversion`. |
| `Monkey Patch/Render/Render2D.cpp` | The main-menu corner text comes from `[Stilwater] MenuText` in `juiced.ini` (default `holdonquietly.com`; empty hides it) and is right-aligned to its length. The 1% "JUICER" easter egg is removed. |
| `Monkey Patch/MainHooks.cpp` | The first-boot welcome popup is Stilwater's and credits the Juiced Team. Its first-boot flag is stored under `HKCU\Software\Stilwater`. Upstream update prompts are disabled. |
| `Monkey Patch/Mem/Memory.cpp` | New `[Stilwater] TreeDistance` (default ×1.5) scales the per-frame tree fade multiplier and the tree chunk limit. New `[Stilwater] ShadowDistance` (default 255 m, vanilla 125) re-enables Juiced's dormant shadow-distance patch. New `[Stilwater] VehicleMemoryScale` (default ×2) enlarges the 8 vehicle streaming slots (vanilla 4 MiB + 3 MiB each) so high-detail car mods can load. |
| `Monkey Patch/General/General.cpp` | The quicksave HUD messages say `STILWATER:`. A `stilwater_<lang>.le_strings` table is loaded ahead of every other string table, so Stilwater mods can add or rename strings. |
| `Monkey Patch/Game/CrashFixes.cpp` | The save-load error title says `STILWATER`. New fix at `0x007B883D`: the Rim Jobs wheel-size preview (`vcust_preview_wheel_sizing`) is skipped instead of crashing when the vehicle being customised is missing. |
| `Monkey Patch/Stilwater/FirstPerson.cpp` (new) | First-person view toggled with `[Stilwater] FirstPersonKey` (default V). Mid-hooks in UpdateCamera: `0x004934F0` moves the new camera position to the player's eyes (object position +0x14, rows at +0x20) before it becomes current; `0x004932F0` restores the game's own position at the next update. PageUp/PageDown tune `FirstPersonEyeHeight` / `FirstPersonVehicleHeight`. On foot, `FirstPersonShowBody` (default 1) turns the actor fade (`0x00E8825F`) off so the body and weapon stay visible, and moves the eyes in front of the face along the camera's view direction. |
| `Monkey Patch/Stilwater/RimJobsGuard.cpp` (new) | Every Rim Jobs script command (`vcust_*`, 16 of them) runs under SEH: if the vehicle being customised is gone, the command returns nothing instead of crashing (adding nitrous crashed at `0x007B90C3`). Installed from `CrashFixes::Init`. |
| `Monkey Patch/Stilwater/Trainer.cpp` (new) | In-game trainer opened with `[Stilwater] TrainerKey` (default F7), single-player only; hooked from `MainHooks.cpp`. |
| `Monkey Patch/Stilwater/Horns.cpp` (new) | Trainer "HORN" entry: changes the horn of the current vehicle's model (u16 index at vehicle entry +0x540) and saves it per model in `[StilwaterHorns]`, reapplied on entering a car. |

## Building

The solution's `Debug|Win32` configuration builds the project's Release configuration into `Release\DFEngine.dll`. This matches upstream CI. `..\build.ps1` does this for you.
