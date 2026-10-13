# Reverse-engineering notes

All addresses are virtual addresses (image base `0x00400000`) in the unencrypted SR2 build that Juiced Patch targets: the Steam exe after Juiced's patch, or GOG.

## Which binary to analyze

- **Steam `SR2_pc.exe` is SteamStub-wrapped.** It has a `.bind` section, its entry point is inside `.bind`, and `.text` is fully encrypted on disk (entropy 8.0). Static analysis of it finds nothing.
- **Analyze the unencrypted build instead.** The exe produced by Juiced's Steam patch works. So does `SR2MP.exe` from SR2 Reloaded, which has the same section layout but contains Reloaded's multiplayer changes, so a few functions differ.
- **Sections:** `.text` 0x401000, `.rdata` 0xDB8000, `.data` 0xE80000.

## Known addresses

| Address | What |
|---|---|
| `0x00520BA0` | `WinMain`. The prologue dword `0x83EC8B55` identifies the unencrypted build. |
| `0x007740F0` | Writes the default display settings: 1024×768, fullscreen. |
| `0x00774112` / `0x0077411C` | Default width and height immediates. Juiced overwrites them with the desktop resolution. |
| `0x00774126` | Default fullscreen byte write. Juiced forces windowed here. |
| `0x00774190` | Startup settings load. Reads the first 0x54 bytes of `settings.dat`, falling back to `0x007740F0` if the file is missing. |
| `0x006970D0` | Full `settings.dat` read, including the multiplayer name and login blocks. |
| `0x00696F50` | `settings.dat` write. |
| `0x01F7A9A0` | Live display settings: width (u32), +0x04 height, +0x08 u32 (default 2), +0x0C fullscreen (u8), +0x0D..+0x17 flags. |
| `0x0144E650` | Save folder path, used as `"%s\\%s"` with `settings.dat`. |
| `0x022F6418` | `d3d_present_params.Windowed` (from Juiced). |
| `0x0252A410` | Game `HWND` (from Juiced). |

## `settings.dat`

Location: `%LOCALAPPDATA%\THQ\Saints Row 2\settings.dat`. Steam Cloud does not sync it; it only syncs `profile.dat` and the saves.

| Offset | Size | Contents |
|---|---|---|
| 0x00 | 0x54 | Display record. Width u32 at +0x3C, height at +0x40, u32 at +0x44 (default 2), fullscreen u8 at +0x48, flags from +0x49. |
| 0x54 | 4 × 0x40 | Multiplayer name and login strings. Each is XORed with `rand()` output after `srand(0xADF0 + i)`, so treat the file as sensitive. |

`profile.dat` holds a copy of the same 0x54-byte display record at offset 0x6DA.

## SR2 Reloaded (`RLEngine.dll` / `reloaded.ini`) options worth porting

- `ExtendedRenderDistance`: render distance ×1.85.
- `ExtendedTreeFadeDistance`: 250000 → 500000.
- `ExtendedShadowRenderDistance`: 125 → 255.

Juiced Patch has no equivalents. `RLEngine.dll` is native code, so analyze it with REA/Ghidra to find the patch sites.
