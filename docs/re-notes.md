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

## Draw distance

These were traced with REA and Ghidra against the unencrypted v9.2.0-target exe.

| Address | What |
|---|---|
| `0x00E996B4` | Render distance multiplier (float, default 1.0). Juiced's `DynamicRenderDistance` adjusts it at runtime. |
| `0x0054DFB0` | Loads the `Shadows` table: `Day_Shadow_Dist` → `0x0279778C` and `Night_Shadow_Dist` → `0x02797790` (both int, vanilla 125), plus ramp times at `0x02797794`–`0x027977A0`. NOPing the 15-byte `mov ecx / mov esi / call` at `0x0054DFDE` and `0x0054DFEE` keeps patched values; the caller cleans the pushed args with `add esp, 0x18`. |
| `0x004D9DD0` | Blends the day and night shadow distances by time of day and applies the result. |
| `0x00A8DAB0` | SpeedTree loader. Per type, stores fade distance², and raises `[0x0252A058]` to the largest fade distance² (vanilla 250000, i.e. 500 m). It never lowers it. |
| `0x00A8FAD0` | Tree render loop. A chunk is drawn if dist² ≤ `[0x0252A058]` × 4. |
| `0x00A8E0F0` | Per-tree fade distance² = type fade² × `[0x02658E78]`, with an FOV adjustment. |
| `0x004D5670` | Time-of-day update, run every frame. It lerps keyframe fields (stride 0x250 from `0x02654314`) into globals, including the tree fade multiplier `[0x02658E78]`, written at `0x004D57AE`. Stilwater scales the multiplier with a mid-hook at `0x004D57B4`, where the x87 stack is empty and the next instruction is a `JL` on earlier flags. |

## Vehicle streaming slots

Streamed vehicles (`.car_pc`, `.g_car_pc`, `.peg_pc`, `.g_peg_pc` and a few optional files, listed per vehicle by `0x00ADAE70`) load into pool 2 of the stream system.

| Address | What |
|---|---|
| `0x0051D800` | Memory setup. `push 0x2000000` at `0x0051F1A5` → `[0x02527324]` (region A buffer), `push 0x1800000` at `0x0051F1B2` → `[0x02527328]` (region B buffer). |
| `0x0051F700` | Stream setup. Builds six 0x30-byte pool records on the stack (`buf A, slot A size, buf B, slot B size, slot count, ...`, then callbacks) and passes them to `0x00A78E60`, which calls `0x00A753C0` per pool. Pool 2 is vehicles: 8 slots, slot A `[esp+0x4C]` = ECX = `0x400000` (stored at `0x0051F7DC`; the same ECX also sets pool 1 at `0x0051F7D8`), slot B `mov [esp+0x54], 0x300000` at `0x0051F872`, callbacks at `0x00ADB4E0` / `0x00ADB9F0` / `0x00ADBA70`. |

Observed limit: the Civic with `.car_pc` + `.g_car_pc` = 4,138,316 bytes spawned; at 4,348,940 bytes it never finished loading (no crash, the player waits forever to get in). The textures (3.1 MB) fit region B. Stilwater scales the buffers and both slot sizes together (`[Stilwater] VehicleMemoryScale`); the pool keeps the sizes it is given, and the vehicle callbacks have no other size checks.

## Horns

| Address | What |
|---|---|
| `0x004883E0` | Reads `foley_horns.xtbl`: horn count (u16) to `0x02526B6C`, table of `count` × 8 bytes to `*(0x00F53078)`: u32 game string hash of `Name` (`0x00BDCB30`, CRC table `0x00E843B8`, lower case), u16 sound id from `HornLoop`. |
| `0x00488640` | Horn name → index. |
| `0x00AE6890`, `0x00AEA1F0` | Vehicle table parsers: `<Horn>` becomes a u16 index at +0x540 of the model's 2000-byte vehicle entry (defaults first, then the model's own). |
| `0x00B40B60` | Sounds the horn: car object +0x84E4 → vehicle entry, entry +0x540 → horn index → table entry +4 → sound. Read every time, so a change takes effect at once. |

Car objects: `*(0x02149C64 + (handle & 0xFFF) * 16)`, handle at object +0x44; the player's vehicle handle is at player +0xD74.

## SR2 Reloaded (`RLEngine.dll` / `reloaded.ini`) options worth porting

- `ExtendedRenderDistance`: render distance ×1.85.
- `ExtendedTreeFadeDistance`: 250000 → 500000.
- `ExtendedShadowRenderDistance`: 125 → 255.

Juiced Patch has no equivalents. `RLEngine.dll` is native code, so analyze it with REA/Ghidra to find the patch sites.
