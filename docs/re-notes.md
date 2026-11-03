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

With all three login strings set, the Co-op → Online menu signs in by itself (`0x008EABB0` → `gpiConnect` at `0x008F1480`). The launcher's Friends page writes them (`launcher/GameLogin.cs`).

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
