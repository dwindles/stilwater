// CoopSize.cpp (Stilwater)
// The game's own co-op with more than two players: [Stilwater] MaxCoopPlayers (4; 2 is the game's
// own, up to 12). With two players everything plays as before.
//
// The engine comes from multiplayer, which takes 12 players: its players are a list (head at
// 0x0217043C) drawn from a pool of 12 (free list at 0x021703D0, 0x009D7C10 hands out slots below
// the lobby cap), scripts know #PLAYER1# to #PLAYER12# (0x00E87CEC), and each remote player's body
// and clothing slots are set up once per remote player (0x009E9EB0, lobby cap - 1 times). What holds
// co-op to two:
//  - the cap: co-op's network setup ("coop-mp", 0x007F7095) writes 2 to the player cap (0x00E8C434)
//    and the lobby cap (0x00E8C438), which matchmaking, the slots above and the player pool read.
//    They're set to MaxCoopPlayers after it (0x007F71F8).
//  - the memory for remote players' characters: three pools, "coop_player cpu" (0x228000 bytes),
//    "coop_allocators" (0x5ADBB0) and "coop_player gpu" (0x1071000), sized for one remote player and
//    carved at fixed places out of one block (0x0051E4FD-0x0051E8B8). Making them bigger in place
//    (what Juiced's Network/NetPlayer.cpp tried) runs into whatever comes after; here each gets
//    memory of its own, sized for MaxCoopPlayers - 1 remote players, where its base is passed (its
//    size was pushed just before).
// The game logic still asks for "the" partner in many places (0x009D7BD0, the first player that
// isn't us; about 330 functions). With more players: while a network message is handled it's
// whoever sent it (with two, the sender always was the partner), on a client otherwise the host's
// player, whom a client's game follows, and on the host the other player in the mission or
// activity going on (a player past two who starts an activity is the one in it), else #PLAYER2#.
// Where it matters, what's done for the partner is done for the others too (below). When #PLAYER2#
// leaves, the next player takes that name over (missions' REMOTE_PLAYER) and the mission's partner
// slot.
//
// Missions: their scripts know two players, LOCAL_PLAYER ("#PLAYER1#") and REMOTE_PLAYER
// ("#PLAYER2#"); a third is "#PLAYER3#" and so on (names by slot, player +0x18B0). On the host,
// what a mission does to REMOTE_PLAYER (teleports, controls, temporary weapons, invulnerability…)
// is done again for every other player: Update wraps those script functions in Lua.
//
// The minimap (0x007A37E0) shows the partner as a blue arrow in online co-op (0x007A3A97-0x007A3BB3):
// 0x0079EC50 puts their position on the map (held at its edge when far), 0x00BE3380 gives their
// heading from their rows (+0x20), and 0x00B87C10 draws the player arrow (0x01F8B298) in the colour
// set by 0x004C7570. The same is drawn for every other player, each in a colour of their own.
//
// Going down instead of dying (0x009AFDD0, asked by the death handler 0x00985370): in co-op a player
// can be revived (30 s, 0x009AF7F0) when the partner is within 1200 m. It asks whoever is nearest
// (the call at 0x009AFEEB); with two players that is the partner. Reviving already takes any downed
// player close by (0x00975720 looks through every human).
//
// Cutscenes hide the partner while they play and revive them if down, then show them again
// after; the same is done for every other player.
//
// Joining: a co-op session is made with room for 2, so a third player was turned away as full.
//
// Leaving: when one player goes, the host undoes everything "the partner" had going and a client
// stops the cutscene. With others still in the game only what was theirs goes: an activity they
// were in, and what they'd asked the host to stream (kept per player here); the cutscene stops for
// the host only. Joins wait their turn while another joiner waits.
#include "CoopSize.h"

#include <Windows.h>
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "../FileLogger.h"
#include "../GameConfig.h"
#include "../General/General.h"
#include "../SafeWrite.h"
#include <safetyhook.hpp>

namespace CoopSize
{
	namespace
	{
		int g_players = 2;
		SafetyHookMid g_cap, g_cpu, g_allocators, g_gpu, g_minimap, g_pauseMap, g_notTheHost, g_missingMember, g_teleportBeside, g_bothOut, g_hostWithRoom, g_roomForMore, g_heldByOther, g_missionStart, g_cutsceneStart, g_cutsceneEnd, g_leftOthersStay, g_cutsceneGoesOn;

		// At a co-op pool's "push ecx" (its base): its size is on top of the stack.
		void Grow(SafetyHookContext& ctx, const char* name)
		{
			uint32_t& size = *reinterpret_cast<uint32_t*>(ctx.esp);
			const uint32_t grown = size * static_cast<uint32_t>(g_players - 1);
			void* memory = VirtualAlloc(nullptr, grown, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
			if (!memory) {
				Logger::TypedLog(CHN_NET, "CoopSize: no memory for {} ({} bytes); it stays sized for one partner.\n", name, grown);
				return;
			}
			Logger::TypedLog(CHN_NET, "CoopSize: {} moved to its own {} bytes ({} remote players).\n", name, grown, g_players - 1);
			ctx.ecx = reinterpret_cast<uintptr_t>(memory);
			size = grown;
		}

		// Co-op settings that test for exactly two players (count at 0x021603CC), "cmp, 2; jne": with
		// three they'd fall back to single player's. Each jne becomes jl (two or more).
		//  0x0090D17D  a limit of 3 instead of 6 (0x0090D110)
		//  0x009292BE  co-op's ambient amount (0x00929280)
		//  0x009413D0  a second spawn category to fall back on (0x009413A0; without it, no group)
		//  0x005251D1  the partner's view (0x005250E0; still only the first partner)
		constexpr uintptr_t ExactlyTwo[] = { 0x0090D17D, 0x009292BE, 0x009413D0, 0x005251D1 };

		// What missions do to REMOTE_PLAYER that every player should get. Left out: seats
		// (player_force_vehicle_seat, vehicle_enter_teleport) one character can hold.
		constexpr const char* Mirrored[] = {
			"teleport", "vehicle_exit_teleport", "vehicle_exit_dive",
			"player_controls_enable", "player_controls_disable", "set_player_can_enter_exit_vehicles",
			"set_player_can_be_busted", "inv_weapon_add_temporary", "inv_weapon_remove_temporary",
			"inv_item_remove_all", "turn_vulnerable", "turn_invulnerable",
			"character_evacuate_from_all_vehicles", "character_set_damage_multiplier",
			"character_set_cannot_wield_havok_weapon", "player_warp_to_shore_enable",
			"player_warp_to_shore_disable",
			// The player second: a weapon a mission hands out, and callbacks a mission sets up for "either
			// player" (registered for LOCAL_PLAYER and REMOTE_PLAYER; "" clears one).
			"inv_item_equip", "on_vehicle_enter", "on_vehicle_exit", "on_weapon_fired", "on_take_damage",
			"on_district_changed", "on_weapon_pickup", "on_weapon_equip",
		};

		// The game's Lua is 5.0: varargs come as arg (arg.n), and there's no unpack, so calls are
		// passed on by count (a trailing nil would change what a native sees).
		constexpr const char* MirrorLib = R"(
if not SW_mirror then
  -- Any argument that is "#PLAYER2#" (REMOTE_PLAYER) is the player; the call is made again with
  -- each other player in its place.
  function SW_call(f, a)
    local n = a.n
    if n == 0 then return f() end
    if n == 1 then return f(a[1]) end
    if n == 2 then return f(a[1], a[2]) end
    if n == 3 then return f(a[1], a[2], a[3]) end
    if n == 4 then return f(a[1], a[2], a[3], a[4]) end
    if n == 5 then return f(a[1], a[2], a[3], a[4], a[5]) end
    if n == 6 then return f(a[1], a[2], a[3], a[4], a[5], a[6]) end
    return f(a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8])
  end
  function SW_mirror(f, a)
    local r1, r2, r3 = SW_call(f, a)
    local k = 1
    while k <= a.n and a[k] ~= "#PLAYER2#" do k = k + 1 end
    if k <= a.n and SW_EXTRA_N then
      local i = 1
      while i <= SW_EXTRA_N do
        local b = { n = a.n }
        local j = 1
        while j <= a.n do b[j] = a[j] j = j + 1 end
        b[k] = SW_EXTRA[i]
        SW_call(f, b)
        i = i + 1
      end
    end
    return r1, r2, r3
  end
end
-- Seats: every vehicle_enter_teleport(character, vehicle, seat) notes the seat it filled; when
-- REMOTE_PLAYER is seated, each other player takes the highest seat no one was put in (not the
-- driver's), so a mission's own passengers keep theirs.
if not SW_seat then
  SW_seats = {}
  function SW_seat(a)
    local r1, r2, r3 = SW_call(SW_orig_vehicle_enter_teleport, a)
    local v = a[2]
    if v then
      if not SW_seats[v] then SW_seats[v] = {} end
      SW_seats[v][a[3] or 0] = true
      if a[1] == "#PLAYER2#" and SW_EXTRA_N and vehicle_get_num_seats then
        local seat = (vehicle_get_num_seats(v) or 0) - 1
        local i = 1
        while i <= SW_EXTRA_N and seat >= 1 do
          if not SW_seats[v][seat] then
            SW_seats[v][seat] = true
            SW_call(SW_orig_vehicle_enter_teleport, { SW_EXTRA[i], v, seat; n = 3 })
            i = i + 1
          end
          seat = seat - 1
        end
      end
    end
    return r1, r2, r3
  end
end
)";

		// Each name: wrapped once per Lua state (a new state brings the game's own function back).
		std::string WrapScript()
		{
			std::string script = MirrorLib;
			for (const char* name : Mirrored) {
				const std::string n = name;
				script += "if " + n + " and " + n + " ~= SW_wrap_" + n + " then SW_orig_" + n + " = " + n +
					" SW_wrap_" + n + " = function(...) return SW_mirror(SW_orig_" + n + ", arg) end " +
					n + " = SW_wrap_" + n + " end\n";
			}
			script += "if vehicle_enter_teleport and vehicle_enter_teleport ~= SW_wrap_vehicle_enter_teleport then "
				"SW_orig_vehicle_enter_teleport = vehicle_enter_teleport "
				"SW_wrap_vehicle_enter_teleport = function(...) return SW_seat(arg) end "
				"vehicle_enter_teleport = SW_wrap_vehicle_enter_teleport end\n";
			return script;
		}

		// The host is the one running the missions: in co-op, with a session we host (session +0x3F8,
		// set by 0x0080C920 when hosting, cleared when joining; new_conn's handler 0x00816D00 skips
		// it). Like the game, 0x02528B56 without 0x02528B2B counts as a client.
		bool IsCoopHost()
		{
			if (*reinterpret_cast<const char*>(0x02528B49) == 0)
				return false;
			if (*reinterpret_cast<const char*>(0x02528B56) != 0 && *reinterpret_cast<const char*>(0x02528B2B) == 0)
				return false;
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
			return session && *reinterpret_cast<const char*>(session + 0x3F8) != 0;
		}

		// Script names of the players past the first two, as a Lua list ("" when there are none).
		std::string ExtraNames(int& count)
		{
			std::string list;
			count = 0;
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				const char* name = *reinterpret_cast<const char* const*>(player + 0x18B0);
				if (name && std::strncmp(name, "#PLAYER", 7) == 0 && std::strcmp(name, "#PLAYER1#") != 0 &&
					std::strcmp(name, "#PLAYER2#") != 0) {
					list += (count ? ", \"" : "\"") + std::string(name) + "\"";
					++count;
				}
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
			return list;
		}

		// Where a world position is on the minimap (eax = position, ecx = how far past its edge,
		// then where to draw and where it would be without the edge).
		void ToMinimap(const float* position, float* xy)
		{
			float past = 0, unclamped[2];
			float* rest = unclamped;
			uintptr_t saved;
			__asm {
				mov saved, esp
				push rest
				push xy
				lea ecx, past
				mov eax, position
				mov edx, 0x0079EC50
				call edx
				mov esp, saved
			}
		}

		float Heading(const float* rows)
		{
			float heading;
			uintptr_t saved;
			__asm {
				mov saved, esp
				mov ecx, rows
				mov eax, 0x00BE3380
				call eax
				movss heading, xmm0
				mov esp, saved
			}
			return heading;
		}

		// While a network message is handled, the player who sent it (0 = none known): with two
		// players the sender was always "the partner", so that's what the handler means by it.
		thread_local uintptr_t t_sender = 0;

		// The player a peer owns: their network object (+0xB0) starts with the peer's id (+0x1B0).
		uintptr_t PlayerOf(uintptr_t peer)
		{
			if (!peer)
				return 0;
			const uint8_t id = *reinterpret_cast<const uint8_t*>(peer + 0x1B0);
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				const auto* object = *reinterpret_cast<const uint8_t* const*>(player + 0xB0);
				if (object && *object == id)
					return player;
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
			return 0;
		}

		// An object by its handle (+0x44; table 0x02149C64, 16 bytes per entry), or 0 when it's gone.
		uintptr_t ByHandle(uint32_t handle)
		{
			if (!handle)
				return 0;
			const uintptr_t object = *reinterpret_cast<const uintptr_t*>(0x02149C64 + (handle & 0xFFF) * 16);
			return object && *reinterpret_cast<const uint32_t*>(object + 0x44) == handle ? object : 0;
		}

		bool IsOtherPlayer(uintptr_t object)
		{
			const uintptr_t local = *reinterpret_cast<const uintptr_t*>(0x021703D4);
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			uintptr_t player = head;
			for (int guard = 0; object && player && guard < 16; ++guard) {
				if (player == object)
					return player != local;
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
			return false;
		}

		// The other player in the mission, stronghold or activity going on (its two slots: who
		// started it 0x02527CA0, the partner 0x02527CA4; a client who starts one is the first). Only
		// while one is going on (its state 0x01450380 isn't 0; the game takes joiners only at 0,
		// 0x00831AC0): the slots can outlast it.
		uintptr_t Participant()
		{
			if (*reinterpret_cast<const int*>(0x01450380) == 0)
				return 0;
			for (const uintptr_t slot : { 0x02527CA0u, 0x02527CA4u }) {
				const uintptr_t object = ByHandle(*reinterpret_cast<const uint32_t*>(slot));
				if (IsOtherPlayer(object))
					return object;
			}
			return 0;
		}

		// The partner, in place of the game's 0x009D7BD0 (about 570 calls): the first player that
		// isn't us, in co-op. While a message is handled it's whoever sent it. A client's game mostly
		// follows the host (a shared vehicle, the mission, cutscenes), so there it's the host's
		// player: the one whose network object (+0xB0) belongs to the host's peer (session +0x404).
		// On the host it's the other player in what's going on (a player past two who starts an
		// activity is in it, not #PLAYER2#), else the lowest #PLAYERn#.
		uintptr_t __cdecl Partner()
		{
			if (*reinterpret_cast<const char*>(0x02528B49) == 0)
				return 0;
			if (t_sender)
				return t_sender;
			const uintptr_t local = *reinterpret_cast<const uintptr_t*>(0x021703D4);
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
			uintptr_t hostPeer = 0;
			if (session && (*reinterpret_cast<const char*>(session + 0x3F8) == 0 ||
				(*reinterpret_cast<const char*>(0x02528B56) != 0 && *reinterpret_cast<const char*>(0x02528B2B) == 0)))
				hostPeer = *reinterpret_cast<const uintptr_t*>(session + 0x404);
			if (!hostPeer)
				if (const uintptr_t participant = Participant())
					return participant;
			// Otherwise (the host), the one with the lowest slot ("#PLAYERn#", +0x18B0): new players go
			// to the front of the list, so "the first" would change to whoever joined last.
			uintptr_t lowest = 0;
			int lowestSlot = 99;
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				if (player != local) {
					if (hostPeer) {
						const char* object = *reinterpret_cast<const char* const*>(player + 0xB0);
						if (object && *object == *reinterpret_cast<const char*>(hostPeer + 0x1B0))
							return player;
					}
					const char* name = *reinterpret_cast<const char* const*>(player + 0x18B0);
					const int slot = name && std::strncmp(name, "#PLAYER", 7) == 0 ? std::atoi(name + 7) : 50;
					if (!lowest || slot < lowestSlot) {
						lowest = player;
						lowestSlot = slot;
					}
				}
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
			return lowest;
		}

		// Each player but us and the partner, in co-op (multiplayer's players are left alone).
		template <typename Fn>
		void ForEachOther(Fn fn)
		{
			if (*reinterpret_cast<const char*>(0x02528B49) == 0)
				return;
			const uintptr_t local = *reinterpret_cast<const uintptr_t*>(0x021703D4);
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			if (!local || !head)
				return;
			const uintptr_t partner = Partner();
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				if (player != local && player != partner)
					fn(player);
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
		}

		// In place of the partner (0x009D7BD0) where going down checks the distance: the other player
		// nearest to us (never none: the caller has checked there is a partner).
		uintptr_t __cdecl NearestOther()
		{
			const uintptr_t local = *reinterpret_cast<const uintptr_t*>(0x021703D4);
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			const float* from = reinterpret_cast<const float*>(local + 0x14);
			uintptr_t nearest = 0;
			float best = 0;
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				if (player != local) {
					const float* at = reinterpret_cast<const float*>(player + 0x14);
					const float dx = at[0] - from[0], dy = at[1] - from[1], dz = at[2] - from[2];
					const float distance = dx * dx + dy * dy + dz * dz;
					if (!nearest || distance < best) {
						nearest = player;
						best = distance;
					}
				}
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
			return nearest;
		}

		// Players past the partner, in the same order on the minimap and the pause map.
		struct Colour { float r, g, b; };
		constexpr Colour Colours[] = { { 0, 200, 80 }, { 255, 140, 0 }, { 190, 80, 255 }, { 255, 230, 0 }, { 255, 60, 140 } };
		const Colour& ColourOf(int n) { return Colours[n % (sizeof(Colours) / sizeof(Colours[0]))]; }
		const auto SetColour = reinterpret_cast<void(__cdecl*)(float, float, float, float)>(0x004C7570);
		const auto DrawArrow = reinterpret_cast<void(__cdecl*)(int, float, float, float, float, const void*)>(0x00B87C10);

		// After the partner's arrow (alpha at [esp+0x10]): one for each player past the first two.
		void DrawOthers(SafetyHookContext& ctx)
		{
			if (*reinterpret_cast<const char*>(0x02528B48) != 1 || *reinterpret_cast<const char*>(0x02528B49) != 1)
				return;
			// Where the partner gets a different marker, the others get none.
			const uintptr_t hud = *reinterpret_cast<const uintptr_t*>(0x02527888);
			if (hud) {
				const uintptr_t state = *reinterpret_cast<const uintptr_t*>(hud + 8);
				if (reinterpret_cast<int(__thiscall*)(uintptr_t)>((*reinterpret_cast<uintptr_t* const*>(state))[2])(state) == 0x18)
					return;
			}
			if (reinterpret_cast<int(__cdecl*)()>(0x00603E30)() == 0x19)
				return;

			const float alpha = *reinterpret_cast<const float*>(ctx.esp + 0x10);
			const float mapScale = (std::max)(*reinterpret_cast<const float*>(0x022DBFA8), *reinterpret_cast<const float*>(0x022DBFAC));
			const bool northUp = *reinterpret_cast<const char*>(0x02528615) != 0;

			int n = 0;
			ForEachOther([&](uintptr_t player) {
				float xy[2];
				ToMinimap(reinterpret_cast<const float*>(player + 0x14), xy);
				float angle = Heading(reinterpret_cast<const float*>(player + 0x20)) + 3.1415927f;
				if (!northUp)
					angle += *reinterpret_cast<const float*>(0x02528620);
				const Colour& c = ColourOf(n++);
				SetColour(c.r, c.g, c.b, alpha * 255.0f);
				DrawArrow(*reinterpret_cast<const int*>(0x01F8B298), xy[0], xy[1], angle, mapScale, reinterpret_cast<const void*>(0x00EC2740));
			});
		}

		// The pause map (0x0076FB00) draws the partner's arrow the same way (0x0077029A-0x0077038C):
		// 0x00771490 (out x,y; world x, z) places it, the arrow is 0x01F7A8D0, alpha (0-255) at
		// [esp+0x14] and the map's zoom at [esp+0x18]. At its start, one for each other player.
		void DrawOthersOnMap(SafetyHookContext& ctx)
		{
			const float alpha = *reinterpret_cast<const float*>(ctx.esp + 0x14);
			const float zoom = *reinterpret_cast<const float*>(ctx.esp + 0x18);
			const float scale = (std::max)(*reinterpret_cast<const float*>(0x022DBFA8), *reinterpret_cast<const float*>(0x022DBFAC)) * zoom;
			const auto ToMap = reinterpret_cast<void(__cdecl*)(float*, float, float)>(0x00771490);
			int n = 0;
			ForEachOther([&](uintptr_t player) {
				const float* at = reinterpret_cast<const float*>(player + 0x14);
				float xy[2] = {};
				ToMap(xy, at[0], at[2]);
				const float angle = Heading(reinterpret_cast<const float*>(player + 0x20)) + 3.1415927f;
				const Colour& c = ColourOf(n++);
				SetColour(c.r, c.g, c.b, alpha);
				DrawArrow(*reinterpret_cast<const int*>(0x01F7A8D0), xy[0], xy[1], angle, scale, reinterpret_cast<const void*>(0x00EC2740));
			});
		}

		// 0x00926860 (ecx = human; hidden, 1, from the owner): hides a human for a cutscene.
		void Hide(uintptr_t human)
		{
			uintptr_t saved;
			__asm {
				mov saved, esp
				push 0
				push 1
				push 1
				mov ecx, human
				mov eax, 0x00926860
				call eax
				mov esp, saved
			}
		}

		// A mission starting (0x006A2680) readies its two players (0x006A80C0, 0x006A8100): lets go
		// of a human shield (0x009CBC60, 0x009CAF90), ends what they're doing (0x00982380,
		// 0x00981E00) and their action node (0x009742A0). Then everyone else.
		void ReadyForMission(uintptr_t human)
		{
			bool shield;
			uintptr_t saved;
			__asm {
				mov saved, esp
				mov eax, human
				mov edx, 0x009CBC60
				call edx
				mov shield, al
				mov esp, saved
			}
			if (shield) {
				__asm {
					mov saved, esp
					push 0
					push 0
					mov ecx, human
					mov eax, 0x009CAF90
					call eax
					mov esp, saved
				}
			}
			if (reinterpret_cast<bool(__cdecl*)(uintptr_t)>(0x00982380)(human)) {
				__asm {
					mov saved, esp
					mov ecx, human
					mov eax, 0x00981E00
					call eax
					mov esp, saved
				}
			}
			reinterpret_cast<void(__cdecl*)(uintptr_t, int)>(0x009742A0)(human, 0);
		}

		// The network update of an object (0x0084D230) treats one the partner holds as a human shield
		// (+0x374, its handle) differently ([esp+0x13]); any other player holding it counts too.
		void HeldByOther(SafetyHookContext& ctx)
		{
			uint8_t& held = *reinterpret_cast<uint8_t*>(ctx.esp + 0x13);
			if (held)
				return;
			const uintptr_t object = *reinterpret_cast<const uintptr_t*>(ctx.esp + 0x88);
			if (!object)
				return;
			const uint32_t handle = *reinterpret_cast<const uint32_t*>(object + 0x44);
			ForEachOther([&](uintptr_t player) {
				if (*reinterpret_cast<const uint32_t*>(player + 0x374) == handle)
					held = 1;
			});
		}

		// A co-op session is made with room for 2 (its settings +0x38, 0x0082FD10), and the host's
		// join_req handler (0x00815BC0) turns away anyone past that as full (deny 3) at 0x00815EDA:
		// peers (+0x3F4) + pending (+0x30) == settings (+0xC) +0x38. Co-op's 2 becomes MaxCoopPlayers.
		void RoomForMore(SafetyHookContext& ctx)
		{
			if (*reinterpret_cast<const char*>(0x02528B49) == 0)
				return;
			const uintptr_t settings = *reinterpret_cast<const uintptr_t*>(ctx.ebx + 0xC);
			if (!settings)
				return;
			int& room = *reinterpret_cast<int*>(settings + 0x38);
			if (room == 2) {
				room = g_players;
				Logger::TypedLog(CHN_NET, "CoopSize: the co-op session now has room for {}.\n", g_players);
			}
		}

		// The co-op lobby's step 8 (0x008303D0) hosts or joins with the settings at 0x00EB223C (filled
		// by 0x0082FD10); they get the same room. Hosting, so the server list (which asks for
		// "numplayers < maxplayers") still shows the game once two are in; joining (flags 0x00EB22CC &
		// 0x12), because everyone connects to everyone (new_conn) and a joined player's session also
		// counts its room (tried 2026-11-03: a second joiner hung while the first's room was 2).
		void HostWithRoom(SafetyHookContext&)
		{
			if (*reinterpret_cast<const int*>(0x00E8C438) != g_players)   // set up for co-op (the cap hook)
				return;
			int& room = *reinterpret_cast<int*>(0x00EB223C + 0x38);
			if (room == 2) {
				room = g_players;
				Logger::TypedLog(CHN_NET, "CoopSize: {} co-op with room for {}.\n",
					*reinterpret_cast<const uint8_t*>(0x00EB22CC) & 0x12 ? "joining" : "hosting", g_players);
			}
		}

		// Dying for real in online co-op (0x00960E40, 0x0096127A-0x009612F5): when the partner dies
		// while we're down we bleed out (0x009AF560), and when both are out the host respawns them
		// (0x008CBD90). Neither while another player is still up (alive, not down) to revive.
		bool AnotherIsUp()
		{
			bool up = false;
			ForEachOther([&](uintptr_t player) {
				if (*reinterpret_cast<const float*>(player + 0x1124) > 0.0f && *reinterpret_cast<const int*>(player + 0xF8C) < 0)
					up = true;
			});
			return up;
		}

		void BothOut(SafetyHookContext& ctx)
		{
			if (AnotherIsUp())
				ctx.eip = 0x009612FA;
		}

		// Joining, in the log: each join message as it arrives (the session's message table at
		// 0x00E8BF18: +8 id, +0xC handler, +0x10 name) and why the host turns one away (0x00816F60,
		// the reason on the stack; it sends join_deny).
		SafetyHookMid g_joinMessages[16], g_joinDenied;

		template <int Id>
		void JoinMessage(SafetyHookContext&)
		{
			Logger::TypedLog(CHN_NET, "CoopSize: got {}.\n", *reinterpret_cast<const char* const*>(0x00E8BF18 + (Id - 1) * 0x18 + 0x10));
		}

		void TraceJoining()
		{
			// join_req, join_acc, join_deny, join_new_session, join_success, join_failed, join_complete,
			// remove_reservation, new_conn, conn_left.
			constexpr struct { int id; void (*log)(SafetyHookContext&); } Traced[] = {
				{ 2, JoinMessage<2> }, { 3, JoinMessage<3> }, { 4, JoinMessage<4> }, { 5, JoinMessage<5> },
				{ 6, JoinMessage<6> }, { 7, JoinMessage<7> }, { 8, JoinMessage<8> }, { 9, JoinMessage<9> },
				{ 10, JoinMessage<10> }, { 12, JoinMessage<12> },
			};
			int n = 0;
			for (const auto& traced : Traced) {
				const uintptr_t entry = 0x00E8BF18 + (traced.id - 1) * 0x18;   // the table starts at id 1
				const uintptr_t handler = *reinterpret_cast<const uintptr_t*>(entry + 0xC);
				if (*reinterpret_cast<const int*>(entry + 8) == traced.id && handler)
					g_joinMessages[n++] = safetyhook::create_mid(handler, traced.log);
			}
			g_joinDenied = safetyhook::create_mid(0x00816F60, [](SafetyHookContext& ctx) {
				Logger::TypedLog(CHN_NET, "CoopSize: turned a join away (reason {}: 2 = no session or same name, 3 = full, 7 = our name).\n",
					*reinterpret_cast<const uint8_t*>(ctx.esp + 4));
			});
		}

		// Whether someone joining is already in the session (0x0080FEB0; eax = session, esi = their
		// address: +4 port, +6 flag, +8 public and +0xC private address; a peer's is at +0x28): the
		// join_req handler silently drops a join from someone who is. The game left the port out, so
		// players on one PC (copies, each on its own port) were all "the same" and only the first got
		// in (tried 2026-11-03). Here the port counts too; packets were always matched with it (0x007FA070).
		__declspec(naked) void FindPeerByAddress()
		{
			__asm {
				push edi
				push ebx
				mov ecx, dword ptr [eax + 0x400]
				mov eax, ecx
				test eax, eax
				je none
			next_peer:
				mov edi, dword ptr [esi + 0xC]
				cmp edi, dword ptr [eax + 0x34]
				jne skip
				mov edx, dword ptr [esi + 8]
				cmp edx, dword ptr [eax + 0x30]
				jne skip
				mov dl, byte ptr [esi + 6]
				cmp dl, byte ptr [eax + 0x2E]
				jne skip
				mov bx, word ptr [esi + 4]
				cmp bx, word ptr [eax + 0x2C]
				je found
			skip:
				mov eax, dword ptr [eax + 0x22CC]
				cmp eax, ecx
				je none
				test eax, eax
				jne next_peer
			none:
				xor eax, eax
			found:
				pop ebx
				pop edi
				ret
			}
		}

		// new_conn (0x00816D00, a client told about another player) first asks whether the announced
		// address is the host's (0x00816DA5-0x00816DC8: private, public, flag) and if so updates the
		// host instead of connecting. Without the port, a player on the host's PC (a copy) was taken
		// for the host: they never connected and the host's record took their details (tried
		// 2026-11-03). At the last compare: a different port (announced at [esp+0x20], the host's at
		// +0x2C, eax = the host's peer) is someone else.
		void NotTheHost(SafetyHookContext& ctx)
		{
			if (*reinterpret_cast<const uint16_t*>(ctx.eax + 0x2C) != *reinterpret_cast<const uint16_t*>(ctx.esp + 0x20))
				ctx.eip = 0x00816DCA;
		}

		// A spawn group's update (0x0090D430: count at [group+4]+0x48, members from group+8) took
		// every member as there; with three players one was missing and the game crashed reading it
		// (2026-11-03, 0x0090D44E). At the top of its loop (0x0090D44B, ebp = the member's slot), an
		// empty one goes on to the next (0x0090D507).
		void SkipMissingMember(SafetyHookContext& ctx)
		{
			if (*reinterpret_cast<const uintptr_t*>(ctx.ebp) != 0)
				return;
			static bool logged = false;
			if (!logged) {
				logged = true;
				Logger::TypedLog(CHN_NET, "CoopSize: a spawn group had a missing member; skipped it.\n");
			}
			ctx.eip = 0x0090D507;
		}

		// One host per co-op game, for as long as it lasts: the session can hand hosting to someone
		// else (migrate 26, migrated 27, post_migration 28, next srv 36; multiplayer's host
		// migration), which in co-op only makes a mess (whose world, whose mission). In co-op their
		// handlers return at once (the dispatcher 0x008138F0 doesn't use what they return; 0x00835864
		// is a lone ret). If the host leaves, the others leave their game instead of taking it over.
		SafetyHookMid g_migration[4];

		void KeepHost(SafetyHookContext& ctx)
		{
			if (*reinterpret_cast<const char*>(0x02528B49) == 0)
				return;
			static DWORD lastLog = 0;
			if (GetTickCount() - lastLog > 5000) {
				lastLog = GetTickCount();
				Logger::TypedLog(CHN_NET, "CoopSize: ignored a host change; the host stays the host.\n");
			}
			ctx.eip = 0x00835864;
		}

		// Each network message's handler, called as handler(data, context) from the dispatcher
		// (0x008138F0, at 0x00813992 / 0x00813A52 / 0x00813ABE) or the ordered queue (0x00813390, at
		// 0x00813457); the sender's peer is at context +4. Each call goes through Handle, which
		// marks the sending player for Partner() and notes their streaming requests.
		thread_local uintptr_t t_handler = 0;
		SafetyHookMid g_handlerCalls[4];

		// The host streams what other players ask for (strm_req 0x73 / strm_rem_req 0x74: key,
		// category, item, 9 bytes; osd_char_strm_req 0x75 / 0x76: key, category, 5 bytes), counted
		// per item with no owner (0x02224430, 0x0215DAC8). So when one player leaves, the game lets
		// go of everything everyone asked for (0x00A7A060, 0x00944EF0). Kept here per player
		// instead: what they still have is let go of with the game's own "no longer needed"
		// (0x00A79360, 0x009444D0), as if they'd sent it.
		constexpr uintptr_t StreamAsk = 0x00A79210, StreamDrop = 0x00A79360, CharAsk = 0x00944490, CharDrop = 0x009444D0;
		struct Asked { uintptr_t peer; bool character; uint8_t data[9]; };
		std::vector<Asked> g_asked;
		CRITICAL_SECTION g_askedLock;

		void NoteRequest(uintptr_t handler, const uint8_t* data, uintptr_t peer)
		{
			const bool ask = handler == StreamAsk || handler == CharAsk;
			const bool character = handler == CharAsk || handler == CharDrop;
			const size_t size = character ? 5 : 9;
			EnterCriticalSection(&g_askedLock);
			if (ask) {
				Asked asked{ peer, character, {} };
				memcpy(asked.data, data, size);
				g_asked.push_back(asked);
			} else {
				// The same thing asked for: key and category (and item) match.
				for (auto it = g_asked.begin(); it != g_asked.end(); ++it)
					if (it->peer == peer && it->character == character && memcmp(it->data, data, size) == 0) {
						g_asked.erase(it);
						break;
					}
			}
			LeaveCriticalSection(&g_askedLock);
		}

		// What a player who left still had asked for, let go of (or everyone's, when the game let go
		// of it all).
		void DropRequests(uintptr_t peer, bool everyone)
		{
			std::vector<Asked> theirs;
			EnterCriticalSection(&g_askedLock);
			for (auto it = g_asked.begin(); it != g_asked.end();)
				if (everyone || it->peer == peer) {
					theirs.push_back(*it);
					it = g_asked.erase(it);
				} else {
					++it;
				}
			LeaveCriticalSection(&g_askedLock);
			if (everyone || theirs.empty())
				return;
			uintptr_t context[2] = { 0, peer };
			for (const Asked& asked : theirs)
				reinterpret_cast<void(__cdecl*)(const uint8_t*, uintptr_t*)>(asked.character ? CharDrop : StreamDrop)(asked.data, context);
			Logger::TypedLog(CHN_NET, "CoopSize: let go of {} things a player who left had asked to stream.\n", theirs.size());
		}

		int __cdecl Handle(const uint8_t* data, uintptr_t context)
		{
			const uintptr_t handler = t_handler;
			const uintptr_t peer = context ? *reinterpret_cast<const uintptr_t*>(context + 4) : 0;
			const bool remote = peer && *reinterpret_cast<const char*>(peer) == 0;
			const bool coop = *reinterpret_cast<const char*>(0x02528B49) != 0;
			if (coop && remote && (handler == StreamAsk || handler == StreamDrop || handler == CharAsk || handler == CharDrop))
				NoteRequest(handler, data, peer);
			const uintptr_t previous = t_sender;
			t_sender = coop && remote ? PlayerOf(peer) : 0;
			const int result = reinterpret_cast<int(__cdecl*)(const uint8_t*, uintptr_t)>(handler)(data, context);
			t_sender = previous;
			return result;
		}

		void ThroughHandle(uintptr_t& reg)
		{
			t_handler = reg;
			reg = reinterpret_cast<uintptr_t>(&Handle);
		}

		// Who's #PLAYER2# on the host: missions' REMOTE_PLAYER. Script names come from a sorted pool
		// of free ones (*0x00EB7F60, count 0x00EB7F68): a new player takes the first (0x009D6AF8,
		// 0x00A52D80), a leaver gives theirs back and the pool is sorted again (0x00A52DA0; the sort
		// 0x006D6390 with 0x00A27B50). So when #PLAYER2# left, #PLAYER3# stayed #PLAYER3# and missions
		// had no REMOTE_PLAYER. The lowest player past two takes #PLAYER2# over, and the mission's
		// partner slot (0x02527CA4) when the one who left had it.
		void SortNames()
		{
			const int last = *reinterpret_cast<const int*>(0x00EB7F68) - 1;
			const uintptr_t pool = *reinterpret_cast<const uintptr_t*>(0x00EB7F60);
			uintptr_t saved;
			__asm {
				mov saved, esp
				push 0x00A27B50
				push last
				push 0
				push pool
				mov ecx, 0x00EB7F60
				mov eax, 0x006D6390
				call eax
				mov esp, saved
			}
		}

		void PromoteLocked();

		// Players come and go on the network thread (0x00862D10), so under its mutex.
		void Promote()
		{
			if (!IsCoopHost())
				return;
			const HANDLE mutex = *reinterpret_cast<const HANDLE*>(0x02A157E4);
			if (!mutex || WaitForSingleObject(mutex, 0) != WAIT_OBJECT_0)
				return;   // next time
			PromoteLocked();
			ReleaseMutex(mutex);
		}

		void PromoteLocked()
		{
			char** pool = *reinterpret_cast<char***>(0x00EB7F60);
			const int count = *reinterpret_cast<const int*>(0x00EB7F68);
			if (!pool || count <= 0 || count > 12)
				return;
			int spare = -1;
			for (int i = 0; i < count && spare < 0; i++)
				if (pool[i] && std::strcmp(pool[i], "#PLAYER2#") == 0)
					spare = i;
			if (spare < 0)
				return;
			const uintptr_t local = *reinterpret_cast<const uintptr_t*>(0x021703D4);
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			uintptr_t next = 0;
			int nextSlot = 99;
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				const char* name = *reinterpret_cast<const char* const*>(player + 0x18B0);
				if (player != local && name && std::strncmp(name, "#PLAYER", 7) == 0) {
					const int slot = std::atoi(name + 7);
					if (slot >= 3 && slot < nextSlot) {
						next = player;
						nextSlot = slot;
					}
				}
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
			if (!next)
				return;
			char*& name = *reinterpret_cast<char**>(next + 0x18B0);
			char* const old = name;
			name = pool[spare];
			pool[spare] = old;
			SortNames();
			uint32_t& partner = *reinterpret_cast<uint32_t*>(0x02527CA4);
			const bool slot = partner && !ByHandle(partner);
			if (slot)
				partner = *reinterpret_cast<const uint32_t*>(next + 0x44);
			Logger::TypedLog(CHN_NET, "CoopSize: {} is now #PLAYER2#, missions' second player{}.\n", old,
				slot ? " (and the mission's partner)" : "");
		}

		// Co-op's "a player left" (0x008CB260, the session's +0xCA4 callback; ebx = their peer, the
		// session at its +0x1AC) was written for one other player. On the host, for someone who was
		// in the game (peer +0x3C == 0xD), it then undoes all a partner had going (0x008CB3A8-
		// 0x008CB409): every remote streaming request (0x00944EF0, 0x00A7A060: counts with no owner),
		// the activity (0x006A8CC0), race, store and HUD states, and it bleeds us out if we're down.
		// On a client, anyone else leaving stops the cutscene (0x006C6B90), which with two meant the
		// host had gone. While others are still in the game neither is right: the host skips that
		// part (a leaver's streaming requests stay until the last one leaves) and a client stops the
		// cutscene only for the host.
		bool OthersStay(uintptr_t session, uintptr_t leaving)
		{
			const uintptr_t first = *reinterpret_cast<const uintptr_t*>(session + 0x400);
			const uintptr_t self = *reinterpret_cast<const uintptr_t*>(session + 0x408);
			uintptr_t peer = first;
			for (int guard = 0; peer && guard < 16; ++guard) {
				if (peer != self && peer != leaving && *reinterpret_cast<const char*>(peer) == 0 &&
					*reinterpret_cast<const int*>(peer + 0x3C) == 0xD)
					return true;
				peer = *reinterpret_cast<const uintptr_t*>(peer + 0x22CC);
				if (peer == first)
					break;
			}
			return false;
		}

		void LeftOthersStay(SafetyHookContext& ctx)
		{
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(ctx.ebx + 0x1AC);
			if (!session || !OthersStay(session, ctx.ebx)) {
				DropRequests(0, true);   // the game lets go of them all
				return;
			}
			Logger::TypedLog(CHN_NET, "CoopSize: a player left; the others play on.\n");
			// An activity they were in ends, as it would have (0x006A8CC0); a mission goes on (the next
			// player becomes #PLAYER2#, Promote).
			const uintptr_t player = PlayerOf(ctx.ebx);
			if (player && (ByHandle(*reinterpret_cast<const uint32_t*>(0x02527CA0)) == player ||
				ByHandle(*reinterpret_cast<const uint32_t*>(0x02527CA4)) == player))
				reinterpret_cast<void(__cdecl*)()>(0x006A8CC0)();
			DropRequests(ctx.ebx, false);
			ctx.eip = 0x008CB42D;
		}

		void CutsceneGoesOn(SafetyHookContext& ctx)
		{
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(ctx.ebx + 0x1AC);
			if (!session || *reinterpret_cast<const int*>(session + 0x1C) == 0)
				return;
			const uintptr_t host = *reinterpret_cast<const uintptr_t*>(session + 0x404);
			if (host && host != ctx.ebx)
				ctx.eip = 0x008CB42D;
		}

		// A script teleport of a player (teleport, 0x00A47310) ends in 0x009DB480 (ecx = the player,
		// [esp] = position, [esp+4] = the navpoint's rows; for someone else's player it asks their
		// game). Missions only have spots for two, so a mirrored teleport puts the third on the
		// second's: players past the partner land a step to the side of it, #PLAYER3# 1.5 m, #PLAYER4#
		// 3 m, along the spot's right.
		void TeleportBeside(SafetyHookContext& ctx)
		{
			if (!IsCoopHost())
				return;
			const char* name = *reinterpret_cast<const char* const*>(ctx.ecx + 0x18B0);
			if (!name || std::strncmp(name, "#PLAYER", 7) != 0)
				return;
			const int slot = std::atoi(name + 7);
			if (slot < 3)
				return;
			static float beside[3];
			const float* at = *reinterpret_cast<const float* const*>(ctx.esp);
			const float* right = *reinterpret_cast<const float* const*>(ctx.esp + 4);
			const float step = 1.5f * static_cast<float>(slot - 2);
			for (int k = 0; k < 3; k++)
				beside[k] = at[k] + right[k] * step;
			*reinterpret_cast<const float**>(ctx.esp) = beside;
		}

		void MissionStart(SafetyHookContext&)
		{
			ForEachOther(ReadyForMission);
		}

		// A cutscene starting (0x006BFB50) hides the partner (0x00926860; for someone else's
		// player it asks their game) and revives them when down or dead (0x009B04D0); then everyone else.
		void CutsceneStart(SafetyHookContext&)
		{
			if (*reinterpret_cast<const char*>(0x02528B49) == 0)
				return;
			ForEachOther([](uintptr_t player) {
				Hide(player);
				const uint32_t handle = *reinterpret_cast<const uint32_t*>(player + 0x44);
				const uintptr_t object = handle ? *reinterpret_cast<const uintptr_t*>(0x02149C64 + (handle & 0xFFF) * 16) : 0;
				const bool found = object && *reinterpret_cast<const uint32_t*>(object + 0x44) == handle && object == player;
				if (!found || *reinterpret_cast<const float*>(player + 0x1124) <= 0.0f || *reinterpret_cast<const int*>(player + 0xF8C) >= 0)
					reinterpret_cast<void(__cdecl*)(uintptr_t, int)>(0x009B04D0)(player, 1);
			});
		}

		// A cutscene ending (0x006C44C0) shows the partner again and gives them back their
		// controls and weapon (0x006BF9F0); then everyone else.
		void CutsceneEnd(SafetyHookContext&)
		{
			ForEachOther([](uintptr_t player) {
				*reinterpret_cast<uint32_t*>(player + 0x80) &= ~0x14u;
				reinterpret_cast<void(__cdecl*)(uintptr_t)>(0x006BF9F0)(player);
			});
		}
	}

	namespace
	{
		// "#PLAYER1# (us), #PLAYER2# (partner, host), ..." for the players list.
		std::string Roster()
		{
			const uintptr_t local = *reinterpret_cast<const uintptr_t*>(0x021703D4);
			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			const uintptr_t partner = Partner();
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
			const uintptr_t hostPeer = session ? *reinterpret_cast<const uintptr_t*>(session + 0x404) : 0;
			std::string roster;
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				const char* name = *reinterpret_cast<const char* const*>(player + 0x18B0);
				std::string tags;
				if (player == local) tags += "us";
				if (player == partner) tags += tags.empty() ? "partner" : ", partner";
				const char* object = *reinterpret_cast<const char* const*>(player + 0xB0);
				if (hostPeer && object && *object == *reinterpret_cast<const char*>(hostPeer + 0x1B0))
					tags += tags.empty() ? "host's" : ", host's";
				if (!roster.empty()) roster += ", ";
				roster += name ? name : "?";
				if (!tags.empty()) roster += " (" + tags + ")";
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head)
					break;
			}
			return roster;
		}
	}

	// Kicking: the pause menu's kick (kick_coop_player, 0x007EEB00) kicks the first peer that isn't
	// us (0x008CA380) through 0x0080F9B0 (eax = session, the peer). Peers: session +0x400, next at
	// +0x22CC, ours at +0x408, name (wide) at +0xCC.
	namespace
	{
		int g_kick = 0;

		std::vector<uintptr_t> OtherPeers()
		{
			std::vector<uintptr_t> peers;
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
			if (!session || !IsCoopHost())
				return peers;
			const uintptr_t first = *reinterpret_cast<const uintptr_t*>(session + 0x400);
			const uintptr_t self = *reinterpret_cast<const uintptr_t*>(session + 0x408);
			uintptr_t peer = first;
			for (int guard = 0; peer && guard < 16; ++guard) {
				if (peer != self)
					peers.push_back(peer);
				peer = *reinterpret_cast<const uintptr_t*>(peer + 0x22CC);
				if (peer == first)
					break;
			}
			return peers;
		}

		std::string PeerName(uintptr_t peer)
		{
			const auto* name = reinterpret_cast<const wchar_t*>(peer + 0xCC);
			char text[64] = {};
			WideCharToMultiByte(CP_UTF8, 0, name, 31, text, sizeof(text) - 1, nullptr, nullptr);
			return text[0] ? text : "?";
		}
	}

	// Joining one at a time: the host's answer to a join request (setup_request 24, 0x00831500 ->
	// 0x00831CA0(data, &offset, context): one byte, the joiner's peer at context +4) keeps the joiner
	// in one global (0x02528D1C) while it waits, for the host's "wants to join" box (0x02528D14) or for
	// the host to be free (0x02528CF3; 0x00831AC0: in the world, no cutscene, no activity). A second
	// request took its place, and the first waited on "Please Wait" for good. Here a request that
	// comes while another waits is kept, and asked again in order once that one is answered or gone.
	namespace
	{
		struct Waiting { uintptr_t peer; char flag; };
		Waiting g_waiting[8];
		int g_waitingCount = 0;
		bool g_replaying = false;
		SafetyHookMid g_joinRequest;

		bool JoinWaits()
		{
			return *reinterpret_cast<const uintptr_t*>(0x02528D1C) &&
				(*reinterpret_cast<const char*>(0x02528CF3) != 0 || *reinterpret_cast<const uint32_t*>(0x02528D14) != 0);
		}

		// 0x00831CA0's entry (network thread): [esp+4] data, [esp+8] &offset, [esp+0xC] context.
		void JoinRequest(SafetyHookContext& ctx)
		{
			if (g_replaying || *reinterpret_cast<const char*>(0x02528B49) == 0)
				return;
			const uintptr_t context = *reinterpret_cast<const uintptr_t*>(ctx.esp + 0xC);
			const uintptr_t peer = context ? *reinterpret_cast<const uintptr_t*>(context + 4) : 0;
			if (!peer || !JoinWaits() || *reinterpret_cast<const uintptr_t*>(0x02528D1C) == peer)
				return;
			for (int i = 0; i < g_waitingCount; i++)
				if (g_waiting[i].peer == peer) {
					ctx.eip = 0x00835864;
					return;
				}
			if (g_waitingCount == 8)
				return;
			const auto* data = *reinterpret_cast<const char* const*>(ctx.esp + 4);
			const int offset = **reinterpret_cast<const int* const*>(ctx.esp + 8);
			g_waiting[g_waitingCount++] = { peer, data[offset] };
			Logger::TypedLog(CHN_NET, "CoopSize: {} asked to join while another player waits; they're next.\n", PeerName(peer));
			ctx.eip = 0x00835864;   // a lone ret: the caller (0x00831531) clears its three arguments
		}

		bool StillJoining(uintptr_t session, uintptr_t wanted)
		{
			const uintptr_t first = *reinterpret_cast<const uintptr_t*>(session + 0x400);
			uintptr_t peer = first;
			for (int guard = 0; peer && guard < 16; ++guard) {
				if (peer == wanted)
					return *reinterpret_cast<const char*>(peer) == 0 && *reinterpret_cast<const int*>(peer + 0x3C) < 0xD;
				peer = *reinterpret_cast<const uintptr_t*>(peer + 0x22CC);
				if (peer == first)
					break;
			}
			return false;
		}

		// Once nobody waits, the next request is asked again (under the network thread's mutex).
		void NextJoiner()
		{
			if (!g_waitingCount || JoinWaits())
				return;
			const HANDLE mutex = *reinterpret_cast<const HANDLE*>(0x02A157E4);
			if (!mutex || WaitForSingleObject(mutex, 0) != WAIT_OBJECT_0)
				return;
			const Waiting next = g_waiting[0];
			--g_waitingCount;
			for (int i = 0; i < g_waitingCount; i++)
				g_waiting[i] = g_waiting[i + 1];
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
			if (session && StillJoining(session, next.peer)) {
				Logger::TypedLog(CHN_NET, "CoopSize: {}'s turn to join.\n", PeerName(next.peer));
				char data[1] = { next.flag };
				int offset = 0;
				uintptr_t context[2] = { 0, next.peer };
				g_replaying = true;
				reinterpret_cast<int(__cdecl*)(const char*, int*, const uintptr_t*)>(0x00831CA0)(data, &offset, context);
				g_replaying = false;
			}
			ReleaseMutex(mutex);
		}
	}

	std::string KickLabel()
	{
		const std::vector<uintptr_t> peers = OtherPeers();
		if (peers.empty())
			return "Kick co-op player\tHost a co-op game";
		g_kick = (g_kick % static_cast<int>(peers.size()) + static_cast<int>(peers.size())) % static_cast<int>(peers.size());
		return "Kick co-op player\t" + PeerName(peers[g_kick]);
	}

	void KickCycle(int direction) { g_kick += direction; }

	void Kick()
	{
		const std::vector<uintptr_t> peers = OtherPeers();
		if (peers.empty())
			return;
		const int count = static_cast<int>(peers.size());
		const uintptr_t peer = peers[(g_kick % count + count) % count];
		const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
		Logger::TypedLog(CHN_NET, "CoopSize: kicking {}.\n", PeerName(peer));
		uintptr_t saved;
		__asm {
			mov saved, esp
			push peer
			mov eax, session
			mov ecx, 0x0080F9B0
			call ecx
			mov esp, saved
		}
	}

	int Players() { return g_players; }

	void Update()
	{
		static DWORD next = 0;
		static std::string last;
		if (g_players == 2 || GetTickCount() < next)
			return;
		next = GetTickCount() + 1000;
		NextJoiner();
		Promote();
		if (*reinterpret_cast<const char*>(0x02528B49) == 0 && !g_asked.empty())
			DropRequests(0, true);   // out of co-op: nothing to keep

		// Who's in the game, logged when it changes (for trying co-op past two).
		static std::string lastRoster;
		const std::string roster = Roster();
		if (roster != lastRoster)
			Logger::TypedLog(CHN_NET, "CoopSize: players {}.\n", roster.empty() ? "(none)" : roster);
		lastRoster = roster;

		int count = 0;
		const std::string names = IsCoopHost() ? ExtraNames(count) : "";
		if (names.empty() && last.empty())
			return;
		if (names != last)
			Logger::TypedLog(CHN_NET, "CoopSize: missions also apply to {} other players ({}).\n", count, names);
		last = names;
		static const std::string wrap = WrapScript();
		General::LuaExecute(("SW_EXTRA = { " + names + " } SW_EXTRA_N = " + std::to_string(count) + "\n" + wrap).c_str());
	}

	void Init()
	{
		g_players = std::clamp(static_cast<int>(GameConfig::GetValue("Stilwater", "MaxCoopPlayers", 4,
			"Most players in the game's own co-op (2 = the game's own; up to 12). Each one past two takes about 25 MB.")), 2, 12);
		if (g_players == 2)
			return;
		g_cap = safetyhook::create_mid(0x007F71F8, [](SafetyHookContext&) {
			*reinterpret_cast<int*>(0x00E8C434) = g_players;
			*reinterpret_cast<int*>(0x00E8C438) = g_players;
		});
		g_cpu = safetyhook::create_mid(0x0051E50D, [](SafetyHookContext& ctx) { Grow(ctx, "coop_player cpu"); });
		g_allocators = safetyhook::create_mid(0x0051E540, [](SafetyHookContext& ctx) { Grow(ctx, "coop_allocators"); });
		g_gpu = safetyhook::create_mid(0x0051E8B2, [](SafetyHookContext& ctx) { Grow(ctx, "coop_player gpu"); });
		g_minimap = safetyhook::create_mid(0x007A3BD8, DrawOthers);
		g_pauseMap = safetyhook::create_mid(0x0077029A, DrawOthersOnMap);
		WriteRelJump(0x009D7BD0, reinterpret_cast<UInt32>(&Partner));
		WriteRelCall(0x009AFEEB, reinterpret_cast<UInt32>(&NearestOther));
		TraceJoining();
		WriteRelJump(0x0080FEB0, reinterpret_cast<UInt32>(&FindPeerByAddress));
		g_notTheHost = safetyhook::create_mid(0x00816DC1, NotTheHost);
		g_missingMember = safetyhook::create_mid(0x0090D44B, SkipMissingMember);
		g_teleportBeside = safetyhook::create_mid(0x00A474AB, TeleportBeside);
		constexpr uintptr_t Migration[] = { 0x008108F0, 0x00810A00, 0x008037E0, 0x00810A20 };   // migrate, migrated, post_migration, next srv
		for (int i = 0; i < 4; i++)
			g_migration[i] = safetyhook::create_mid(Migration[i], KeepHost);
		g_bothOut = safetyhook::create_mid(0x0096127A, BothOut);
		g_hostWithRoom = safetyhook::create_mid(0x008305EA, HostWithRoom);
		g_roomForMore = safetyhook::create_mid(0x00815EDA, RoomForMore);
		g_heldByOther = safetyhook::create_mid(0x0084DA28, HeldByOther);
		g_missionStart = safetyhook::create_mid(0x006A281C, MissionStart);     // after the partner's
		g_cutsceneStart = safetyhook::create_mid(0x006C0584, CutsceneStart);   // after the partner's
		g_cutsceneEnd = safetyhook::create_mid(0x006C563C, CutsceneEnd);
		g_leftOthersStay = safetyhook::create_mid(0x008CB3A8, LeftOthersStay);   // host, someone in the game left
		g_cutsceneGoesOn = safetyhook::create_mid(0x008CB428, CutsceneGoesOn);   // client, someone else left
		g_joinRequest = safetyhook::create_mid(0x00831CA0, JoinRequest);         // host, one joiner at a time
		InitializeCriticalSection(&g_askedLock);
		g_handlerCalls[0] = safetyhook::create_mid(0x00813457, [](SafetyHookContext& ctx) { ThroughHandle(ctx.eax); });  // ordered queue
		g_handlerCalls[1] = safetyhook::create_mid(0x00813992, [](SafetyHookContext& ctx) { ThroughHandle(ctx.eax); });  // no session yet
		g_handlerCalls[2] = safetyhook::create_mid(0x00813A52, [](SafetyHookContext& ctx) { ThroughHandle(ctx.eax); });  // session messages
		g_handlerCalls[3] = safetyhook::create_mid(0x00813ABE, [](SafetyHookContext& ctx) { ThroughHandle(ctx.edx); });  // gameplay messages
		int checks = 0;
		for (uintptr_t at : ExactlyTwo)
			if (*reinterpret_cast<const uint8_t*>(at) == 0x75) {   // JNE rel8
				SafeWrite8(at, 0x7C);                              // JL rel8
				checks++;
			}
		Logger::TypedLog(CHN_NET, "CoopSize: {} of 4 two-player checks now take two or more.\n", checks);
		Logger::TypedLog(CHN_NET, "CoopSize: co-op takes {} players.\n", g_players);
	}
}
