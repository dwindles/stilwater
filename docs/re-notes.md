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
| 0x54 | 4 × 0x40 | Online login, in this order: password, nick, email, LAN name (`0x212ABC8`, `0x212AB48`, `0x212AC08`, `0x212AB08`). Each is XORed with the low byte of successive MSVC `rand()` values after `srand(0xADF0 + i)` (`0x00696F20`), so treat the file as sensitive. |

`profile.dat` holds a copy of the same 0x54-byte display record at offset 0x6DA.

The sign-in box comes up filled in from them, but the game itself never signs in without "Log into" (see "Signing in to online co-op"); Stilwater does it at start. The launcher's Friends page writes them (`launcher/GameLogin.cs`).

## Online (OpenSpy / GameSpy Presence)

The core points GameSpy's hosts at OpenSpy (`Patches/OpenSpy.cpp`), or at Stilwater Online (`Stilwater/OnlineServer.cpp`). SR2's GameSpy identity, from the GP connection set up at `0x008EDCC0` and the login message built at `0x008F1990`:

| Field | Value |
|---|---|
| Game name | `srow2pc` (`0x00DD0DAC`) |
| Product id | 11405 (connection +0x60C) |
| Namespace id | 1 (+0x610) |
| Partner id | 0 (+0x1A4) |
| SDK revision | 11 |

Login is by `nick@email` (no unique nick). `launcher/Online.cs` speaks the same protocol for the friends list and invites.

Hostnames the game uses (all rewritten to `openspy.net` by `Patches/OpenSpy.cpp`): `%s.available`, `%s.master`, `%s.ms%d` (server browser), `natneg1`-`3`, `gpcm`, `gpsp`, `motd` (HTTP), and the HTTP services `%s.auth.pubsvs` (AuthService, login certificates), `%s.sake` (storage) and `%s.comp.pubsvs` (competition). It resolves them with WSOCK32 `gethostbyname` (ordinal 52, IAT slot `0x00DB8338`); `Stilwater/OnlineServer.cpp` hooks that slot to send every `*.openspy.net` / `*.gamespy.com` lookup to `[Stilwater] OnlineServer`. Stilwater Online (`server/`) doesn't serve the HTTP services yet; co-op isn't known to need them.

Server browser (SB v2), from the game's parser:

- Secret key `odvimE`, built on the stack before both `ServerBrowserNew` calls (`0x008D0180`, `0x00811C30`). `ServerBrowserNew` is `0x008E59B0`; it copies the game name to +0xC and +0x30 and the key to +0x54.
- Crypt header (`0x008E7EB0`): byte 0 = n XOR 0xEC, then n bytes whose first two are backend flags (read at +1, byte-swapped, kept at +0x7D0; 0x80 = query challenge), then a byte = m XOR 0xEA and m bytes of server challenge. Key mix `0x008E78B0`: `key[(secret[i % len] * i) & 7] ^= key[i & 7] ^ server[i]` over the 8-byte client challenge, then GOACryptInit (Sapphire II) on those 8 bytes.
- List body: client IP (4), default query port (2, 0xFFFF = an error string follows), key count, per key type (0 string, 1 byte, 2 short) and name, popular-value count and strings, then entries until `00 FF FF FF FF`.
- Entry (`0x008E7D00`): flags, IP (4); 0x10 port (2), 0x02 private IP (4), 0x20 private port (2), 0x08 ICMP IP (4); 0x40 values (strings as 0xFF + text or a popular index, checked by `0x008E79C0`), 0x80 full rules. 0x01 = takes unsolicited UDP, 0x04 = connect through NAT negotiation.
- NAT negotiation magic `FD FC 1E 66 6A B2` at `0x00DD0DB4`.

### The online layer (GameSpy core, `0x008CB000`–`0x008D5000`)

- Start, at game start: `0x0051D800` → network init `0x00809570` → `0x00809CA0` → `0x008CCD60`: makes "gamespy_pool" (0x400), registers five modules (`0x008CD0D0`, module in esi, refused when its vtable +0x18 says its dependencies are missing), sets `0x02529331` (started) and state 1, which checks `%s.available` (`0x008D47E0`; state handler `0x008CCB20`: available → "Initializing Modules." `0x008CC8A0`, `0x02529332` set, state 2; unavailable → error 2 or 3, state 0). `0x008CD060` shuts it down.
- State `0x02529334`, written only through `0x008CDCE0` + "Set state to %u." (`0x008CCA60` and inline copies): 0 off or service down, 1 checking the service, 2 ready / not signed in (also after a failed sign-in), 3 signing in, 4 signed in. Error `0x02529338` ("Set error to %u."): 2 and 3 service down, 4 sign-in failed or timed out.
- Pump `0x008CCEB0`, called first thing in the network frame `0x00809D10` (and from `0x0081A440`, `0x0081A590`): the sign-in result (above), drops to state 2 when a module says so, per state: 1 → `0x008CCB20`, 3 → `0x008CCC20` (20 s timeout, then error 4; state 4 once modules `0x00EB4B00` and `0x00EB4AD0` both report ready, `0x008CE520` / `0x008D11D0`), 4 → keep-alive; then every module's think.
- Modules, a circular list at `0x0252933C` (count `0x02529340`). Vtable: +0 init (pool), +4 think, +8 shutdown, +0xC reset (before each sign-in), +0x10 disconnect ("Disconnecting Modules." `0x008CC9F0`, after a failure), +0x14 connect, +0x18 dependencies met. Their constructors run from the CRT init table, so the decomp misses them.

| Object | Vtable | Module |
|---|---|---|
| `0x00EB44B8` | `0x00E33228` | Account: connect `0x008CF510` opens the logging-in box and checks nick/e-mail/password on gpsp (search type 5, `0x008EB090` → `0x008F8A60`; gpsp `0x008F8380`) |
| `0x00EB4AD0` | `0x00E33434` | GP presence on gpcm: login (`0x008D10D0` → `0x008EABA0` → gpiConnect `0x008F1480`), friends, status, blocks, keep-alive, logout |
| `0x00EB4B00` | `0x00E32DF0` | AuthService LoginProfile (login certificate, `0x008E8FB0`, RSA key `0x00DD0C78`) and the competition (stats) service |
| `0x00EB50F8` | `0x00E3340C` | Game list and hosting: init `0x008CFE50` names the custom keys 0x32-0x3D (ranked, mode, variant, mapid, maxplayers, open_slots, session, password, gameplay_mode, online_name, custom_game, gamever); hosting starts QR2 in `0x008D0AB0`; list results `0x008CF970` / `0x008CF770` ("%s (%d/%d)") |
| `0x00EB5140` | `0x00E33508` | Sake storage (user_page_storage, user_file_storage) |

- Log: `0x008CBF50` formats "GAMESPY: %u] CORE: %s" (states, errors, modules, NAT negotiation: "Got NAT_START", "NAT negotiation complete", "Kicking %ls due to failed NAT.", "Not needed, both were on the same subnet, using private addr", ...). Juiced's `UGC/InternalPrint.cpp` already puts it in debug.txt as `[INTERNAL]` lines.
- Services and the code that builds their addresses: available `0x008D47E0`, `%s.master` (QR2: a host's heartbeats, qr2_init `0x008E1940`), `%s.ms%d` (the server browser) `0x008E7010`, AuthService `0x008E8FB0` (+ `0x008E93F0` / `0x008E9820` / `0x008E9B50` for other login kinds), competition `0x008DF7D0`, sake `0x008DE200`, natneg1-3 `0x00905E90`, gpcm `0x008F1230`, gpsp `0x008F8380`, motd/vercheck `0x0090B490` / `0x0090B730`.

## Audio (XACT banks)

`audio.vpp_pc` holds XACT 3 banks (`.xsb` sound banks, `.xwb` wave banks, version 44) without cue names. `foley.xtbl` names each sound and its bank (`<AudioBanks>`), but its order is not the cue order. The cue numbers come from `audio_boot.idx_map` and `audio_level.idx_map` in `meshes.vpp_pc`: text files listing each bank (`"Weapons"	146`) and then every cue as index and name. The foley parser (`0x00479740`) calls `0x00481D20` with the sound's name and bank; `0x00470230` finds the bank, and `0x0046F8F0` looks the name up by its string hash (`0x00BDCB30`) in the table the idx_map loader (`0x0046FA40`) builds, stripping " Debug" from bank names. For example `MAC10_FIRE_PLAYER` is Weapons cue 109, a looping play of wave 37 (cue 25, which an earlier build replaced by mistake, is `FLAMETHROWER_LOOP`). Automatic weapons loop their fire cue while the trigger is held and play the release cue after it. `tools/sr2/xsb.py` decodes sound banks (cues, sounds, events) and `waves_of(game, bank, cue)` gives a named cue's waves; `tools/sr2/xwb.py` replaces waves with PCM. A loose `Weapons.xwb` loads (an in-memory bank; the loose file loader logs it).

## Item meshes (`.smesh_pc`)

Weapons and item props such as the phone share one layout (`tools/sr2/weaponport.py`). After each detail level's part record the header holds a positions-only shadow mesh: strip length at record +0x28, vertex count at +0x3C (12-byte positions), positions from the 16-byte boundary after record +0x48, then the strip from the next boundary. The game casts the item's shadows (onto itself too) from it, so a replaced model needs it replaced.

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

## Strings

The key of a `.le_strings` entry is the game's string hash of the key name (e.g. `CUST_ITEM_HOODY`): CRC-32 of the lower-cased name starting from 0 with no final inversion (table `0x00E843B8`, `0x00BDCB30`); `tools/sr2/strings.py` `key_hash`.

## Lights (towards underglow)

Cutscene lightsets (`*-Lightset.xtbl` in `common.vpp_pc`; one in SS01-02 is a green light under Mr. Sunshine's car named `SUSH_Underglow`) are parsed by `0x004C8B80` into up to 128 sets at `0x02652198` (16 bytes each: id, records, count, ...; count `0x02526D44`). Each set holds 0x50-byte entries whose lights are 0x90-byte records:

| Offset | Field |
|---|---|
| +0x00 | name |
| +0x08 | u16 type: 0 omni, 2 circular spotlight |
| +0x0C | colour (3 floats); +0x18 multiplier; +0x1C colour × multiplier |
| +0x28 | flags: 0x4000, 0x100 LightLevel, 0x200 LightCharacter, 0x400 ShadowLevel, 0x800 ShadowCharacter |
| +0x2C | position (and a copy at +0x38) |
| +0x5C | direction (from the orientation) |
| +0x68, +0x70 | hotspot, attenuation (start, end) |
| +0x78 | slate name hash |
| +0x80, +0x84, +0x88 | objects the light is attached to (array, capacity, count; filled by cutscene code around `0x006C0F40`) |
| +0x8C | handle collected by `0x004C8A40` (the lights attached to a given object, up to 16) |

`Vehicle-Customization-Lightset.xtbl` is loaded at `0x007B9396`. The vehicle "light" managers (`vehicle_sirenlight_manager` vtable `0x00E467C4`, headlight `0x00E4664C`, brakelight `0x00E466B4`, base `0x00E465F4`) drive glares (`glares.xtbl` coronas such as `SR SirenBlue 01`, name table at `0x00E877C0`), which don't light the ground. Not found yet: the function that turns a light record into a dynamic light.

## Characters for extra co-op players

Each player past the game's own two gets a character that copies what they do on their PC, so the
game needs a way to spawn a character, switch its AI off and move it.

| Address | What |
|---|---|
| `*(0x021703D4)` | The local player (human object). Position at +0x14, orientation matrix at +0x20 (right, up, forward rows), the same layout as vehicles. |
| `0x0098E400` | Spawns an NPC from a character table entry near the player (Juiced's `SpawnNPC`, `ecx` = character id from `GetCharacterID`, pushes `*(0x021703D4)`); Juiced's hook at `0x0098EE0B` captures the new object. |
| `0x0095F090` | Teleports a human to a position (Juiced's `TeleportNPC`: `eax` = human, pushes position, -1, 0). |
| `0x00966720` | Never die (`__stdcall` human, flag). |
| `0x00A52BB0` | Lua script name → human (`ecx` = name, `eax` = 0). `0x00A52CA0` / `0x00A52CD0` are Juiced's name → NPC / vehicle. |

The mission scripts' Lua functions (491 of them) are registered by one function around
`0x00A50000` that fills a table of {name, handler} pairs (`mov [esp+n], name` then
`mov [esp+n+4], handler`); `D:\tools\sr2-re\lua-natives.json` lists them all. The ones that matter
here, with what their handlers do once the name is resolved:

| Lua function | Handler | Calls |
|---|---|---|
| `turn_invulnerable` / `turn_vulnerable` | `0x00A48040` / `0x00A483D0` | `0x00965F40(human, 1)`, then `0x00966090(human, flag)` |
| `set_ignore_ai_flag` | `0x00A44A90` | Flips bit 3 of byte +0x103 of the object (list at +0xF8) |
| `move_to_do` | `0x00A3A870` | Arguments: character, navpoint name, speed (1 walk, 2 run, 3 sprint when the character has the animations, checked through `0x006EA0A0` states 0x5C/0x61). Sets up the character with `0x009707C0`, then orders the move with `0x0099DD20` (`eax` = target position, the navpoint +0x1C; `edx` = flags word; pushes human, speed, -1, flags), keeps the order id at human +0x53C (counter `0x00E87D1C`) and returns it. |
| `turn_to_do` | `0x00A48190` | |
| `teleport` / `teleport_vehicle` | `0x00A47310` / `0x00A47540` | |
| `vehicle_enter_do` | `0x00A494E0` | |
| `npc_combat_enable` | `0x00A2C700` | |
| `set_attack_player_flag` / `set_dont_attack_me_on_sight_flag` | `0x00A43BA0` / `0x00A448F0` | |
| `npc_detection_enable` / `npc_hearing_enable` | `0x00A2D900` / `0x00A30B40` | |
| `release_to_world` | `0x00A42040` | |

## SR2 Reloaded (`RLEngine.dll` / `reloaded.ini`) options worth porting

- `ExtendedRenderDistance`: render distance ×1.85.
- `ExtendedTreeFadeDistance`: 250000 → 500000.
- `ExtendedShadowRenderDistance`: 125 → 255.

Juiced Patch has no equivalents. `RLEngine.dll` is native code, so analyze it with REA/Ghidra to find the patch sites.

## Co-op past two players, natively (started 2026-11-02)

| Address | What |
|---|---|
| `*(0x0217043C)` | Head of the game's player list (circular: next at +0x1294, script handle at +0x18B0). The engine's own list, from multiplayer (12 players); `player_names_get_all` (0x00A41070) walks it. |
| `0x00E87CEC` | Script player names `#PLAYER1#` … `#PLAYER12#` (12 entries), copied into the script name table by 0x00A535E0. |
| `0x021703D4` | Local player (3120 code references, single-player code). `0x0217043C` has 243. |
| strings | `coop_player cpu/gpu`, `coop_allocators`, `hack_coop_allocators` (memory sized for one remote player), `coop_stress_test_member_*` console commands, `kick_coop_player`, `coop_is_active` (UI script table, refs 0x7F0184 / 0xA4FA52). |

Next: find code that takes "the other player" as `head->next` or a fixed remote pointer instead of walking the list; the co-op allocators (one remote player's memory); the session's player cap (Juiced's commented NetPlayer.cpp patches: 0x007F750D, 0x0086ACF5, 0x007F7522, 0x007F7A31).

### Findings, 2026-11-03

| Address | What |
|---|---|
| `0x009D7BD0` | "The partner": first player in the list that isn't the local one, when co-op (`0x02528B49`) is on. About 330 callers. |
| `0x009D7C10` | Takes a player from the pool of 12 (free list `0x021703D0`, 0x18F0 bytes each), only slots below the lobby cap; `0x021603CC` counts players. |
| `0x007F7095` / `0x007F71EC` / `0x007F71F2` | Co-op's network setup ("coop-mp") writes 2 to the player cap `0x00E8C434` and lobby cap `0x00E8C438`. Multiplayer writes 12 (`0x007F750D`), system link 12/8 (`0x007F732C`). |
| `0x0051E4FD` / `0x0051E530` / `0x0051E8A2` | Co-op memory pools for the remote player, fixed offsets in one block: "coop_player cpu" 0x228000, "coop_allocators" 0x5ADBB0, "coop_player gpu" 0x1071000 (pool objects `0x02773F0C`, `0x02773FC0`, `0x02773F68`). |
| `0x009E9EB0` | Remote players' body/clothing slots (0x58 per player), set up lobby cap − 1 times: already general. |

Stilwater/CoopSize.cpp ([Stilwater] MaxCoopPlayers, default 4) raises the cap and moves the three pools to memory of their own sized for the extra players. Untested with 3 people.

The minimap (`0x007A37E0`, alpha at `[esp+0x10]`) draws the partner's arrow only in online co-op (`0x02528B48 == 1 && 0x02528B49 == 1`, `0x007A3A97`-`0x007A3BB3`): `0x0079EC50` (eax = world position, ecx = out "how far past the edge" 0-1; stack: out drawn x,y held at the map's edge, out x,y without the edge) places it, `0x00BE3380` (ecx = rows, +0x20; heading in xmm0) + pi (+ `0x02528620` unless north-up `0x02528615`) turns it, `0x004C7570` (r, g, b, a; 0-255 floats) colours it (partner 0, 99, 255) and `0x00B87C10` (texture `[0x01F8B298]`, x, y, angle, scale = max(`0x022DBFA8`, `0x022DBFAC`), `0x00EC2740`) draws it. When the HUD state is 0x18 or `0x00603E30` is 0x19 the partner gets `0x0079EFC0` instead. `0x0079F890` (player) draws a player's followers (+0xC3C count, handles from +0xC40, 0x18 apart), for us and the partner only. CoopSize draws the arrow for every other player at `0x007A3BD8`.

Going down in co-op: the death handler `0x00985370` asks `0x009AFDD0` whether the dying human goes down instead. In co-op that's yes when we aren't already down (our `+0xF8C < 0`) and we're within 1200 m of the partner (squared distance < `[0x00DD09F0]`, partner from the call at `0x009AFEEB`). Going down (`0x009AF7F0`) sets `+0xF8C` to now + 30 s (scaled by a difficulty value outside online co-op; 15 s or 0 in some activity states) and sends message 0x68/7. The local player's countdown shows as COOP_REVIVAL_PENDING (`0x009D7611`). Who can be revived: `0x00975720` looks through every human (`0x0215E908`), not only the partner. Mission end (`0x006A0080`) clears `+0xF8C` for us and the partner and stands them up (`0x0092D4B0`). Each machine does this for its own player. CoopSize makes the `0x009AFEEB` call return the nearest other player.

Cutscenes and players: a cutscene (struct `0x02527D10`) begins in `0x006BFB50`, which `0x006C3BA0` sets as the cutscene state's step `0x02527D18`. It hides us (`0x009661E0`) and, in co-op, the partner, through `0x00926860` (ecx = human; stack: hidden, 1, force). That sets `+0x80` bit 0x10, or for another machine's player sends 0x6D/0x14 to its owner. It then revives the partner (`0x009B04D0(human, 1)`; with 0 it sends 0x68/6) when down (`+0xF8C >= 0`), dead (`+0x1124 <= 0`) or not found by handle. The cleanup `0x006C44C0` puts us back and, at `0x006C561B`, clears the partner's `+0x80 & 0x14` and restores them (`0x006BF9F0`: controls, weapon, `+0x758`). CoopSize does both for every other player (`0x006C0584`, `0x006C563C`).

Who "the partner" is on a client: `0x009D7BD0` returns the first player in the list that isn't us. On a client with more than one other player, that may not be the host, though a client's game mostly follows the host (shared vehicle at `0x006A1440`, mission state, cutscenes). A player's network object `+0xB0` starts with its owner peer's id. The host's peer is session `+0x404`, with its id at `+0x1B0` (the same check that's inlined throughout, e.g. `0x009AF7F0`). CoopSize replaces `0x009D7BD0` with a jump to its own Partner(): on a client it returns the host's player, otherwise the first other player as before.

Mission start (`0x006A2680`) readies the owner (`0x006A80C0`) and partner (`0x006A8100`, from `0x02527CA4`). It releases a human shield (`0x009CBC60`, eax = human; `0x009CAF90`, ecx = human, (0, 0)), ends the current action (`0x00982380(human)`, `0x00981E00` ecx = human) and clears the action node (`0x009742A0(human, 0)`). Moving players into place is the mission script's job (teleport, mirrored by CoopSize). `0x006A1440` only saves our own position and vehicle for a restart. CoopSize readies everyone else at `0x006A281C`.

Network update of an object (`0x0084D230`): `[esp+0x13]` at `0x0084DA28` says whether the partner holds it as a human shield (partner `+0x374` == object handle). CoopSize also sets it for any other player holding it.

Pause map (`0x0076FB00`): the partner's arrow (`0x0077029A`-`0x0077038C`, online co-op) uses `0x00771490` (out x,y; world x; world z), texture `[0x01F7A8D0]`, colour 0,99,255 with alpha `[esp+0x14]` (0-255), and scale max(`0x022DBFA8`, `0x022DBFAC`) × zoom `[esp+0x18]`. It has no map rotation. CoopSize draws the others at `0x0077029A`.

Kicking: `kick_coop_player` (`0x007EEB00`) kicks `0x008CA380` (the first peer that isn't ours) through `0x0080F9B0` (eax = session, peer). Peer name (wide) at `+0xCC`. The Trainer tab's "Kick co-op player" picks any peer.

Dying for real in online co-op (`0x00960E40`): the co-op respawn is a pair. `0x008CBDB0` (esi = human) reads our respawn timer `0x00EB4494` or the partner's `0x00EB4490`. When the partner dies while we're down we bleed out (`0x009AF560`, sends 0x68/8), and when both are out the host respawns them (`0x008CBD90` → `0x0055F330(0, 0)`). Each game only looks at itself and its partner (on a client, the host). The block is `0x0096127A`-`0x009612F5`. CoopSize skips it (to `0x009612FA`) while any other player is still up (`+0x1124 > 0`, `+0xF8C < 0`), so a downed player waits to be revived instead.

Joining past two: the co-op lobby (state `0x00EB2238`, result `0x00EB2234`, flags `0x00EB22CC`) hosts at step 8 (`0x008303D0`). Its settings at `0x00EB223C` are filled by `0x0082FD10`, where room `+0x38` = 2 when flags & 1, else 12 (8 for one ranked mode). It then hosts with `0x0080C920` (edx = settings), or joins with `0x0080C970` / `0x0080CA40` (flags & 2 / & 0x10). The host's `join_req` handler (`0x00815BC0`; message table `0x00E8BF18` entries are +8 id, +0xC handler, +0x10 name) denies with `0x00816F60(reason)`:
- 7 — our own name.
- 2 — no session, or a peer already has that name (`+0x4C`); a client shows this as COOP_HOST_BUSY (`0x00831EC0`).
- 3 — full: peers `+0x3F4` + pending `+0x30` == settings `+0x38` at `0x00815EDA`, or the accept callback `+0xCB4` (`0x00835850`, which only asks anything in multiplayer) says no.

The server list asks for `numplayers < maxplayers`. CoopSize raises co-op's room of 2 to MaxCoopPlayers when hosting (`0x008305EA`) and at the full check. What a host advertises comes from QR2's key callback `0x008CFB90` (registered in `0x008D0AB0`, below): maxplayers is that same room (settings `+0x38`) and open_slots the room less peers and pending, so a raised room is what the list shows; the player count (`0x008CFD80`) is peers + pending.

The partner's view (`0x005250E0`) gathers what's in view of one remote player's camera into a local buffer (`0x00523EB0`); not repeated for others, since whether a second call adds to or replaces it isn't known.

Callers of the partner function looked at so far: `0x007A37E0` minimap blip (one partner), `0x006A2140` cutscene start (records local + partner handles at `0x02527CA0`/`CA4`), `0x005250E0` runs only when exactly two players exist (`0x021603CC == 2`; streaming or camera around the other player, the biggest risk for a third), `0x0084D230` network object update (partner's vehicle), `0x00A3F970` script value at +0xC3C for player and partner.
`0x005250E0`'s two-player branch: `0x009DFA00` gives a player's camera (local: `0x025F5B14`/`0x025F5B38`; remote: position +0x12A0, rows +0x12AC), and `0x00523EB0` gathers what's in view of the partner's camera (screen size +0x12D0/+0x12D4) through `0x00A01AD0`. Per-player visibility, not world streaming; for more players it would run once per remote player.

### Missions' two participants

A mission (or stronghold, activity) has two participant slots: the owner's handle `0x02527CA0` and the partner's `0x02527CA4`. Starts fill them (`0x0069E080`, `0x006A29B0`, `0x006A70D0`, `0x005B73A0`; owner = whoever started, partner = `0x009D7BD0`), `0x006A1C70` (mission end) clears both, and `0x006A8100` returns the partner's human from `0x02527CA4` (type 1, alive flag +0x3CC). 24 references to `0x02527CA4`; with a third player the mission only knows two of them. `0x0069DEE0` is the "join this mission?" box shown to the partner (MISSION_COOP_CONFIRM_*).

`0x006A1440` (mission start state) copies the partner's position and orientation (+0x14, +0x20 rows) when the local player is the client; the third player would need the same.

Partner callers by subsystem (`D:\tools\sr2-re\partner_callers.csv`, 327 callers, 121 with strings): activities (most of them: demo derby, heli assault, piracy, crowd control, sewage, zombie uprising, fuzz, fight club, hitman, trafficking, vandalism, pimping, racing, insurance fraud, escort, tow, taxi, chop shop), missions (`0x0069DEE0`–`0x006A9F10`), cutscenes (`0x006C44C0`), pause map and taxi (`0x0076F0C0`, `0x00771D20`), confessional (`0x007A8C60`), clothing streaming (`0x00610970`, `0x009E6030`), HUD cancel prompts (`0x004FB4C0`), co-op server messages (`0x008CBA50`), stores (`0x00A6A530`), render (`0x005250E0`).

### Co-op network: already a mesh of peers

The session object is `*(0x02528C14)`; its peers are a circular list at +0x400 (0x22D8 bytes each, next +0x22CC, previous +0x22D0), with +0x404 the host's peer and +0x408 our own. +0x3F8 != 0 means we host (0x0080C920 sets it when hosting, 0x0080C970 / 0x008260C0 clear it when joining); the game also counts 0x02528B56 without 0x02528B2B as a client.
- `0x00814740` (message, length; session in edi) sends to every peer but ourselves through `0x00814670` (per-peer send, sequence byte at peer +0x16D4 + channel). About 500 game functions call it, so game messages already reach every player. `0x00814620` is the same loop for another send.
- Message types (table at 0x00E8BF18, 0x18 bytes each: id, handler, name): join_req … join_complete (2–8), new_conn 10 (`0x00816D00`), upd_conn, conn_left, rop_* (replicated objects with owners), migrate / next srv (host migration), nat, voice.
- `0x0080DEC0` (connection state machine): the host sends join_failed / join_complete (`0x00816740` / `0x008168A0`) to every peer; a client sends to the host. new_conn's handler runs only on clients: it decodes the announced address and, unless it's the host's, connects to it. So clients connect to each other too (a mesh), as in 12-player multiplayer.
- Names of players come from a sorted pool (`0x00EB7F60`, count `0x00EB7F68`): a new player takes the lowest free #PLAYERn# (+0x18B0), a leaving one gives it back (`0x00A52DA0`). If player 2 leaves, player 3 stays #PLAYER3#.
- Checks for exactly two players in co-op (`0x021603CC == 2`): `0x0090D110` (limit 3 instead of 6), `0x00929280` (co-op ambient amount), `0x009413A0` (second spawn category), `0x005250E0` (partner's view). CoopSize makes them two or more.
- `0x0080F9B0` takes a peer out of the list on disconnect, for any number of peers.
So the transport isn't what limits co-op to two; the caps, memory pools and "the partner" logic above are.

### How scripts name players

ug_lib.lua: `LOCAL_PLAYER = "#PLAYER1#"`, `REMOTE_PLAYER = "#PLAYER2#"` (PLAYER_TAG_LIST goes to 8). 167 scripts use REMOTE_PLAYER about 1,000 times and `coop_is_active` 366 times; none use #PLAYER3#. `0x00A52BB0` (name in ecx) finds a player by walking the player list and comparing the name at player +0x18B0; each player's name comes from the #PLAYER1#…#PLAYER12# table by slot (`0x00A535E0` / `0x00A52DA0`). Natives such as `teleport` (`0x00A47310`) resolve their target through it.
Plan for 3+: mirror action natives called on "#PLAYER2#" onto #PLAYER3#…#PLAYERn# at the native dispatcher; give queries ("is remote dead/in area") an any/all rule.

### Signing in to online co-op

- Sign-in fields, read from settings.dat at start (`0x006970D0`; 64 bytes each): e-mail `0x0212AC08`, password `0x0212ABC8`, name `0x0212AB48` (the menu's result strings 0, 1, 2).
- Co-op > Online (main_menu.lua `main_menu_maybe_show_coop_online`): when `is_connected_to_service()` is false, on PC it shows the sign-in box (`Main_menu_multiplayer_sign_in_to_gamespy`, the "Enter OpenSpy ID" box) if `is_connected_to_network()` is false, else calls `login_to_online_network(true)`. Both natives (`0x007EEC90`, `0x007EED00`) just return state == 4, so on PC the box always shows until signed in. `user_has_online_privlage` (`0x007EED30`) is always true. `show_login_window_pc` / `show_password_window_pc` (`0x00B90E40` / `0x00B90E60`) open the text entry only for an empty name or e-mail.
- The box's "Log into" = `try_and_login_to_gamespy` (`0x007EE490`) → `0x008CD260`; `login_to_online_network` (`0x007EED70` → `0x0080A150`) opens its own dialog (`0x02528BD0`, finished by `0x00809D10`) and calls `0x008CD260` too; invite and join paths reach `0x0080A150` from C++. All of these natives are registered in `0x007EFA10`, and Ghidra's auto-analysis missed most of them as functions (only reached through that table).
- `0x008CD260`: from state 0 or 2: clears the error, sets `0x0212A5EB` (the menu wants the result), resets each module (vtable +0xC), connects them if not yet (`0x008CC9A0`, "Connecting Modules.", vtable +0x14; `0x02529333` = connected), state 3 with a 20 s deadline (`0x00EB5318`). Returns 1 without doing anything in state 3 or 4, 0 in state 1.
- The GP module's connect (`0x008CF510`) opens "SYSTEM_LOGIN / SYSTEM_LOGGING_IN" with Cancel (`0x00753650`, handle `0x02527FEC`; Cancel → `0x008CD450`) and connects with the saved fields (`0x008EB090`).
- Result, in the pump (`0x008CCEB0`), only while `0x0212A5EB` is set: state 4 → closes the logging-in box and calls Lua `after_gamespy_loggin` (`0x007536E0`, main_menu.lua: `main_menu_restore()`), then "MULTI_LOGIN / LOGIN_SUCCESSFUL" (`0x00760DE0`); state 2 → closes it and shows LOGIN_BAD_NICK / LOGIN_BAD_EMAIL / LOGIN_BAD_PASSWORD / LOGIN_ERROR by GP error `0x0213CCF0` (0xE02 / 0xE01 / 0xE03). Then it clears the flag.
- Stilwater (`OnlineServer::Update`): once the online layer has started and is in state 2 (the service answered; in state 0 the modules were never set up), at least 5 s after start, signs in with the saved login quietly: it skips the logging-in box (call at `0x008CF584`) and clears `0x0212A5EB` after the call, so neither box shows. Pressing "Log into" while that is still going (state 3) opens the box and sets the flag (hook at `0x007EE490`), so it ends the way the menu's own sign-in does. If it fails, once more after 30 s.
- `try_and_create_profile` (`0x007EE4A0` → `0x008CD360`): 666 when the two passwords differ, then GP new user (`0x008EB180`); GP error 0x201 / 0x202 picks the message.

### More copies on one PC (Stilwater/SecondCopy.cpp, launcher --second-copy / --third-copy / --fourth-copy)

- Single instance: `0x00BFA620` makes a mutex and quits when it exists (`jne` at `0x00BFA6B6`); copies 2-4 jump past.
- Save folder: WinMain `0x00520BA0` builds %LOCALAPPDATA%\THQ\Saints Row 2 into `0x0144E650` (copied at `0x00520FCD`); all 16 uses (saves `.bbsave`, `profile.dat`, `settings.dat` with the online sign-in, `input.bin`) go through it. Copies append `\Second copy`, `\Third copy` or `\Fourth copy` at `0x00520FD5`.
- Ports: GameSpy's UDP sockets move on when their port is taken: from 6500 up to 6599 (`0x008F1230` → `0x008DA870` → `0x0090A590`, which binds one exact port), and `0x008E1D50` tries 100 from its base. The game's own socket (`0x00C1BBA0`, co-op traffic; Juiced binds it to any address at `0x00C1BC76`/`0x00D2526F`) is UDP on a fixed 4200 (0x1068) with SO_REUSEADDR. So every copy got 4200 and joins hung on "Loading co-op" (tried 2026-11-03: the host's GameSpy saw both joiners, used their private addresses, then cancelled after ~11 s). Copy N now binds 4200 + N - 1 (bind import slot hooked).
- Juiced's `Gamespy::isSessionCoop` told co-op by room == 2; it now also takes MaxCoopPlayers' room.
- A peer's address is at `+0x28`: +0 the address packets come from, +4 port, +6 a flag, +8 public, +0xC private. Incoming packets are matched to peers on the first 8 bytes, port included (`0x007FA070`). From an unknown sender only types 2 and 5 (join_req, join_new_session) are read (`0x00813BA0`). But "already in the session?" (`0x0080FEB0`; eax = session, esi = address), which the join_req handler uses to silently drop a join, compared only +6, +8 and +0xC. So with copies on one PC only the first joiner got in (tried 2026-11-03: the host got the second joiner's packet and never answered). CoopSize replaces it with one that also compares the port.
- new_conn (`0x00816D00`) asks whether the announced player is the host (`0x00816DA5`-`0x00816DC8`: host peer `+0x34`, `+0x30`, `+0x2E` against the announced address at `[esp+0x1C]`). If so it updates the host's peer instead of connecting. Without the port, the second copy took the third for the host: they never connected (the host saw everyone, 2 and 3 not each other), and 2's record of the host got 3's details. CoopSize jumps to `0x00816DCA` when the ports (`+0x2C`, `[esp+0x20]`) differ.
- With three players a spawn group's update (`0x0090D430`, called from `0x00910DA0`) crashed on an empty member slot (`0x0090D44E`, reading +0x34 of 0). Which copy, and why the slot was empty, isn't known yet; CoopSize skips empty slots at the top of that loop (`0x0090D44B` → `0x0090D507`) and logs it. Many other functions walk the same members (`0x0090DCA0`, `0x0090E7B0`, `0x0090FAA0`, `0x009118D0`, …).
- Our own address, as told to others, always says port 4200. The functions that make it (`0x00811A70`-`0x00811CA0`) each do `mov word [reg+4], 0x1068`, with immediates at `0x00811AC4`, `0x00811B15`, `0x00811BA8`, `0x00811C11`, `0x00811C7E`, `0x00811CBB`. (`0x00812C3D` is a debug address and `0x00814882` the LAN broadcast.) The host learns real ports from packets, but after new_conn two joined players go through GameSpy's NAT step ("same subnet, using private addr") and use that self-reported port. So copy 2 sent copy 3's packets to 4200, the host (tried 2026-11-03). Copies write their own port into those six.
- That wasn't all: when a peer's public address equals ours, GameSpy's NAT step (`0x008CDA00`, "Not needed, both were on the same subnet, using private addr") sets its address to the private one and the port to 4200 (`0x008CDA38`/`0x008CDA3B`). That's right for another PC behind the same router, where the announced port is the router's. For copies on one PC it sent everything to the host, and the host then dropped the third player (conn_left) when the second couldn't reach them. SecondCopy keeps the announced port (`0x008CDA33` → `0x008CDA49`) when the private address is this PC's and the port is a copy's (4200-4203). The other branch ("Already have an open path to this connection") also matches peers by address without the port.
- Session messages, ids 0-48 (layout below, under "How co-op runs"): ping, pong, join_req … join_complete, remove_reservation, new_conn, upd_conn, conn_left, badcon (13, `0x007FBCF0`: only notes a word and a time on the sender's peer at `+0x21F4`/`+0x21F8`), rop_create/destroy/update, dc_ack_list, voice, qos, clock, bw_info, snd_lmt, down_lmt, setup_request/response, migrate (26, `0x008108F0`), migrated (27, `0x00810A00`), post_migration (28, `0x008037E0`), modify/modified session, ext_data, upd state, ack reply, heartbeat, no connect, next srv (36, `0x00810A20`), bull_taco, acks, rop_take_own (39), rop_req_own (40), rop_own_deny, rop_new_owner, global_sync, create_ack, pcjoininfo, gamespyid (46), nat (47, 48). The dispatcher `0x008138F0` calls handler(data, ctx) and ignores what it returns. In co-op CoopSize makes the four host-migration handlers return at once, so the host stays the host.
- Audit of what reaches players past two (2026-11-03):
  - Gameplay messages (second table: entry for id at `0x00E8B6A8` + (id*3 - 0x96)*8, handler +4, name +8; e.g. 0x5C gameplay_changed `0x0068FD40`, 0x5E mssn_req, 0x67 hud_pkt, 0x68 human_pkt, 0x6B scrpt_pkt, 0x6F cutscn_pkt `0x006BECA0`).
  - Every direct send (`0x00814670`, esi = the peer) in a function that also asks for the partner goes to an object's owner (`0x0080FE80`) or the host (session `+0x404`; `0x006A2680`'s mission request). Everything else is broadcast (`0x00814740`). Nothing is sent to the partner only.
  - Cutscenes are broadcast (`0x006BE8F0`-`0x006BEBB0`, 0x6F types 0-5), and the handler starts them for whoever gets one (`0x006C3BA0`). A player not connected at that moment misses it.
  - The host keeps one "other player's gameplay state" (`0x00E96C04`, from gameplay_changed), so with several joined players it's whoever reported last.
  - Mission scripts: deaths don't fail missions (scripts only watch NPCs with on_death). teleport_coop teleports REMOTE_PLAYER (mirrored). cutscene_play / mission_end_success take two warp points, and a third player gets the second's. Not mirrored on purpose: queries (get_dist…, character_is_in_vehicle), vehicle_enter_teleport / player_force_vehicle_seat (seats), party_add. Mirrored with the player in any argument: inv_item_equip, and on_vehicle_enter/exit, on_weapon_fired/pickup/equip, on_take_damage, on_district_changed (registered for both players, so "either player").
- Script teleport (`teleport` native `0x00A47310`): navpoint position at nav `+0x1C`, rows at `+0x28`. A player goes through `0x009DB480` (ecx = player, [esp] = position, [esp+4] = rows; for another machine's player it sends that player's game a request), called at `0x00A474AB`. On the host CoopSize shifts #PLAYER3#+ 1.5 m per slot along the navpoint's right. Seats: `vehicle_enter_teleport(character, vehicle, seat)`. The Lua layer notes the seats each call fills, and seats players past two in the highest unused seats (not 0, the driver's; `vehicle_get_num_seats`) when REMOTE_PLAYER is seated.
- On the host, "the partner" was the first in the list, and new players go to the front, so it changed to whoever joined last. Partner() now takes the lowest #PLAYERn# on the host.
- This PC's name resolves to a link-local Tailscale address first (169.254.x), which is what GameSpy advertises as the private address.
- Sockets: WSOCK32 by ordinal; sendto (20) slot `0x00DB8390`, recvfrom (17) `0x00DB8388`, bind (2) `0x00DB8360`. Every copy lists its UDP ports in shared memory (Local\StilwaterCopies4, 4 entries); a packet to a public address on a port another running copy uses goes to 127.0.0.1, and replies from 127.0.0.1 show the public address again (so routers without NAT loopback work).
- The master server lists every co-op host to a player who isn't pinned to one, so the second copy joins through Pause > Co-op > join an online game; pins are per IP, so both copies follow a launcher Join.

### How co-op runs, end to end (mapped 2026-11-03)

**Session settings** (`0x0082FD10`, from the lobby flags `0x00EB22C8` / `0x00EB22CC`): `+0x30` kind (2, or 1 with flag 0x80; becoming host with 2 sets `0x02528B2B`), `+0x38` room (flag 1 = co-op: 2, else 12; 8 in one ranked mode), `+0x3C` who gets in (flag 8: 0, 0x20: 2, 0x40: 1, else 3), `+0x34` = (`+0x3C` == 3).

**Advertising a hosted game** (QR2, `0x008D0AB0`: qr2_init `0x008E1940` with "srow2pc", the key `odvimE` built on the stack, public, NAT negotiation on). Key callback `0x008CFB90` (jump table `0x008CFD50`) answers the custom keys 0x32-0x3D: ranked (`0x00810C50`), mode (`0x0212E2C8`), variant / mapid (multiplayer only), maxplayers = settings `+0x38`, open_slots = that − peers `+0x3F4` − pending `+0x30`, session, password (whether one is set), gameplay_mode (`0x00E8B210`), online_name (`0x0212AA08`), custom_game (`0x00E8B20C` == 3), gamever 201. Count callback `0x008CFD80`: players = peers + pending. Key list `0x008CFA50`.

**Message tables.** Session messages: entry for id N (0-48) at `0x00E8BF08 + N*0x18`; gameplay messages: id N (0x32-0x81) at `0x00E8B6A8 + (N-0x32)*0x18`. Entry: +0 id, +4 handler(data, ctx), +8 name, +0xC kind (0/1/2; the dispatcher doesn't read it), +0x12 byte: needs a known sender, +0x13 byte: handled with no session too, +0x14 ordered channel (0 = handled at once, else queued through `0x00813470`). The dispatcher `0x008138F0`: a sender that isn't connected (peer `+0x4A` == 0) counts as unknown; nothing is handled before our own peer exists (`+0x408`). Gameplay messages, with handlers: lbby_upd `0x00841F20`, player_respawn `0x0082B6C0`, mp_respawn, req_name, set_team, req_team, play_audio `0x00818A80`, player_score_upd, gb_change, braveheart_packet, expl! `0x0083CC70`, veh_dmg `0x0087A940`, wpn_ammo_change, mover_fade / mover_dmg / mover_active `0x0084E560`-`0x0084EA60`, var upd `0x0083BCF0`, rem console, req_score_change, player_morph `0x0082BAA0`, player_components `0x0082BD00`, veh_cust `0x0087AF30`, cli_trigger_activate `0x00881BD0`, stats_upd / stats_final, game_cond, game_clock `0x0068A450`, weather `0x004DE670`, avail_lvls, trees_destroyed, join_coop (0x50, `0x008324F0`), matchmaking … lobbyreturn (0x51-0x58), ctrl_mode_change, player_control `0x009DFDB0`, mp_info, gameplay_changed (0x5C) / gameplay_denied, mssn_req (0x5E) `0x006A8AD0`, race_req, osd_sync `0x00944970`, actn_reqs, door_event `0x0091AB10`, actn_node, scrpt_start_game, gsi, notor_pkt `0x0055EDF0`, hud_pkt / human_pkt / human_pkt_in_ord / veh_pkt / scrpt_pkt / act_packet / misc_packet (0x67-0x6D, `0x008CA2A0`-`0x008CA360`), memb_pkt, cutscn_pkt (0x6F), chunk_swap_packet `0x00A7C470`, notor_active, strm_set_change / strm_req / strm_rem_req (0x72-0x74, `0x00A79D60` / `0x00A79210` / `0x00A79360`), osd_char_strm_req / _rem_req (0x75-0x76), multi common misc, melee `0x009810C0`, persona `0x006ACD60`, pm_objective, screen_fade `0x004D1610`, block_load, tutorials, streaming_sync `0x00A83F30`, arb_mover, pausing `0x008CB110`, vi (0x81).

**Callbacks a session runs**, set per mode by `0x00819620` (co-op's set first, then two more for the other modes): `+0xC88` its host is gone → `0x008CB450` → `0x008CBA50` (leave the session `0x0080CB30`, "COOP_DISCONNECTED_FROM_SERVER" with the partner's name, back to our own game); `+0xC8C` / `+0xC90` / `+0xC94` migration started / done / failed: empty in co-op; `+0xCA4` a player left → `0x008CB260`; `+0xCB4` accept a join → `0x00835850`.

**Joining, on the host.** A join request is session message setup_request (24, `0x00831500`: the first byte picks a handler from `0x0212FBB0`, set by `0x00832420`; 0 → `0x00831CA0(data, &offset, context)`, one byte, the joiner's peer at context +4). It keeps the joiner in one global, `0x02528D1C` (their GameSpy profile id in `0x0212FD94`), which only "a player left" clears (`0x008329B0`). Who gets in by settings `+0x3C`: 2 at once, 1 when GP says they're friends (`0x00831C40`), otherwise the host gets a box with the joiner's name (`0x00831B40`, handle `0x02528D14`; answer `0x00832360`). The answer is setup_response (25, `0x00831540`, ecx = 0; its body from `0x0212FBA8`). When the host can't take them yet (`0x00831AC0`: co-op, in the world (game state 5 or 6), no cutscene, no activity `0x01450380`, `0x00750500` false), `0x02528CF3` marks the join as waiting, and `0x00832970` answers once the host is free. With one global, a second request while the first waited took its place, and the first waited on "Please Wait" for good. CoopSize keeps such requests (hook at `0x00831CA0`, back to the caller through the lone `ret` at `0x00835864`) and asks them again in order (calling `0x00831CA0` under the network mutex) once nobody waits, if the joiner is still there.

**Players.** The player pool is a static array at `0x02CD0590` (12 × 0x18F0; slot = (player − that) / 0x18F0), taken by `0x009D7C10` only below the lobby cap. Another machine's player is made from a network packet in `0x00862D10` (position, wide name, …; reached through a table) and named by slot (above).

**Someone leaving** (`0x0080F9B0`, eax = session, the peer pushed): the session's `+0xCA4` callback runs for each gone player. If it was the host's peer (`+0x404`), co-op's `+0xC88` runs first and we leave too, so the multiplayer host migration that follows in the same function (`0x0080CEB0` / `0x0080CF50`, session state 10 in `0x0080D510`, the election `0x0080EA20` that sets `+0x3F8` / `+0x404` to us and sends migrate, the successor named by next srv at `+0xA10`) doesn't happen in co-op. CoopSize's KeepHost (ignore migrate / migrated / post_migration / next srv) stays as a guard. Co-op's "a player left" (`0x008CB260`, ebx = their peer) was written for one other player:
- On the host it shows "%s left" (peer state `+0x3C` ≥ 7), does that peer's cleanup (`0x00819880`, esi = peer), recounts notoriety (`0x0055F3F0`) and, for someone who was in the game (`+0x3C` == 0xD, not a waiting joiner), undoes all a partner had going (`0x008CB3A8`-`0x008CB409`): the mission box and the activity (`0x006A8CC0`), "completion_coop_disconnected" (`0x00750B20`), every remote character / streaming request (`0x00944EF0` over `0x0215DAC8`, `0x00A7A060` over `0x02224430`; counts per item, not per player, so it can't tell whose they were), a store lock (`0x00A6CE10`, `0x02529E14`), race state (`0x00682BD0`, sets `0x00E96C04` to 3), two HUD/diversion states (`0x00544F10`, `0x005BBB70`), `0x00A269C0`, and bleeds us out when we're down outside a mission (`0x009AF560`).
- On a client anyone else leaving stops the cutscene (`0x006C6B90`: cutscene struct `0x02527D10` +0x160C, cleanup `0x006C44C0`).
- With more players, CoopSize skips the host's part (to `0x008CB42D`) while another remote peer is still in the game (state 0xD), so the others keep their streaming, activity and revives. Instead it ends an activity the leaver was in (`0x006A8CC0`: in a co-op activity, state `0x01450380` == 4, it fails with MISSION_PARTNER_DISCONNECTED), and lets go of what the leaver had asked to stream. A client stops the cutscene only when the one who left is the host.
- Streaming for others, on the host: strm_req (0x73, `0x00A79210`: key, category, item; 9 bytes) asks locally (`0x00A79120`, ecx = item, edi = key) and counts in `0x00A78D40` (edi = key; entries of 0x24 bytes from `0x02224430`: key, item, 7 counts by category); strm_rem_req (0x74, `0x00A79360`, the same 9 bytes) lets go (`0x00A79240`, edx = key) and counts down (`0x00A78DB0`). osd_char_strm_req / _rem_req (0x75 / 0x76, `0x00944490` / `0x009444D0`: a name hash and a category, 5 bytes; entries of 8 dwords from `0x0215DAC8`). A client asks the host only (`0x00A79120` sends to session `+0x404`). Nothing says who asked, so CoopSize keeps each player's outstanding requests and plays the "no longer needed" handler with the same bytes for a leaver's.
- Who "the partner" is now (CoopSize's Partner()): every handler call (`0x00813457` in the ordered queue `0x00813390`, context = {&peer +0x28, peer}; `0x00813992`, `0x00813A52`, `0x00813ABE` in the dispatcher) goes through a wrapper that marks the sender's player (their network object `+0xB0` starts with the peer's id `+0x1B0`), and Partner() returns them while the handler runs: with two players the sender always was the partner. So a request from a player past two (mssn_req 0x5E → `0x006A8680`, which makes the requester the owner `0x02527CA0` and the host the partner `0x02527CA4`; race, action and trigger requests) is theirs, not #PLAYER2#'s. Otherwise, on the host, the other player in the mission or activity going on (`0x02527CA0` if it's someone else's, then `0x02527CA4`), else the lowest #PLAYERn#.
- Script names past a leave: the free names are a sorted pool (`*0x00EB7F60`, count `0x00EB7F68`, room `0x00EB7F64`; filled with the 12 by `0x00A535E0` from `0x00E87CEC`). A new player takes the first (`0x009D6AF8` in player setup, `0x00A52D80`); a leaver's goes back and the pool is sorted (`0x00A52DA0`; `0x006D6390`(pool, 0, last, `0x00A27B50`), ecx = `0x00EB7F60`). On the host, when #PLAYER2# is free and someone is #PLAYER3# or above, CoopSize gives the lowest of them #PLAYER2# (missions' REMOTE_PLAYER), puts their old name back, and gives them the mission's partner slot when it pointed at someone gone.

**Joined players reaching each other** (only with three or more: with two there's just the host and one other). When someone joins, the host makes a NAT "edge" between them and each other joined player who has a different internet address, when either needs a NAT step (`0x008CD4F0`, "Adding edge"; free list `0x0213CCF8`, waiting `0x0213CCF4`). The host's pump starts each waiting edge (`0x008CC3F0`, "Starting NAT between %ls and %ls") when neither player is negotiating (`+0x47`) and both list each other (`+0x40`, bit = the other's id `+0x1B0`): a random cookie goes to both in session message 47 "nat" (`0x008CD660`: type 0 NAT_START, from the host only; type 1 NAT_FINISH, to the host; type 2 next negotiation). Each side runs GameSpy's negotiation (`0x008CD910`, NNBeginNegotiation `0x00906000`; Stilwater Online pairs any two by cookie, `server/natneg.py`), and when it's over (`0x008CC090`) reports success if that player is reachable (`+0x46` and `+0x1B8`), which traffic from them also makes true ("Failed to negotiated but I've received traffic."). On a failed report the host kicks the newer of the two (higher `+0x1B0`): "Kicking %ls due to failed NAT." at `0x008CD779` / `0x008CD79D` (`0x00817470`, ecx = peer).
- What decides whether the pair keeps talking, on each side: the NAT callback `0x008CC1F0` (result, the other's address as the NAT server saw it, the record: `+0xC` peer). It always sets `+0x46` (done) and `+0x2240` (last heard, minus 5 s). On success the peer's address becomes the NAT server's view (`+0x28` / `+0x2C`) and `+0x1B8` = 1. On failure: if anything has come from them (`+0x48`, set for every packet from a matched peer at `0x00813C39` in `0x00813BA0`), "Failed to negotiated but I've received traffic." and `+0x1B8` = 1; else "Failed to negotiated." and `+0x1B8` = 0. The report to the host (`0x008CC090` → `0x008CBFD0`) says success when `+0x46` and `+0x1B8`.
- `+0x1B8` is "send to this peer": the per-peer send `0x00814670` skips a peer without it. new_conn sets it (`0x00816F15`), so does the host's join_req (`0x00816087`). It also goes to 0 when the peer runs out of packet buffers (`0x007FA400`: `0x007F8810` gives each peer at most 128; unanswered ones pile up when nothing comes back) and after 60 s without hearing from them (`0x007FA9E0`, 15 s while migrating; then `0x008105B0` drops them).
- On the host, a peer that becomes ready (`0x00811D70`) gets `+0x46`; if the host can't queue its NAT edges (no free edge, `0x008CD4F0` returns 0), `+0x1B8` = 0.
- So with no direct way, everything hinges on a packet getting through before NAT negotiation gives up. CoopRelay (`Stilwater/CoopRelay.cpp`) makes that certain: joined players say hello to each other through the host (and answer), and once both relay, their packets go through the host from the first one, until a direct probe each second shows the direct way works both ways. NAT negotiation's packets always go direct. It also skips the kick. Received packets are checked by `0x00813AD0` (the message blocks must add up exactly; byte 6 counts blocks), so a game without CoopRelay drops relay packets (their byte 6 is 0xFF). The game's socket is `*0x00E824C0`, read on the network thread `0x00814320` (select, then `0x00C1C690` → `0x00C1BD10`: recvfrom into a 0x516-byte buffer, then `0x00C1AD60` with the host-order address) under the mutex `*0x02A157E4`, sent from the main thread (`0x00C1B540`).

**Other drops.** "COOP_MAY_HAVE_DROPPED" (`0x008CA4F0`): a peer not heard from for 20 s (`+0x1A4`, last heard) gets a HUD warning with their name. Losing the GameSpy sign-in during online co-op (`0x0069A090`): the host closes the session and drops one peer (`0x008CA380`, the first that isn't ours); a client disconnects (`0x008CBA50`).

**Hooks checked against the code** (2026-11-03): every CoopSize site starts on an instruction boundary and reads what the next instruction does (registers and stack slots). Every redirect lands on the same stack depth (BothOut's skipped flag is set again before its next use at `0x00961469`; the migration handlers are cdecl, so `ret` at `0x00835864` is right). The partner function `0x009D7BD0` already clobbers eax, ecx and edx, so Partner() may too. The game functions called from C++ are cdecl with plain `ret` (`0x0080F9B0` is `ret 4`, called with esp saved). The teleport hook only sees players (`0x00963540` picks the player branch). The two-player checks compare `[0x021603CC]` against 2 (`0x009292B8` uses ecx = 2), so jne → jl keeps two or more on the co-op side. FindPeerByAddress matches the original apart from the port, so a friend who rejoins from a new port is a new peer while the old one times out.
