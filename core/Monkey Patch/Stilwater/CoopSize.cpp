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
// isn't us; about 330 callers): with more players those see one of them.
//
// Missions: their scripts know two players, LOCAL_PLAYER ("#PLAYER1#") and REMOTE_PLAYER
// ("#PLAYER2#"); a third is "#PLAYER3#" and so on (names by slot, player +0x18B0). On the host,
// what a mission does to REMOTE_PLAYER (teleports, controls, temporary weapons, invulnerability…)
// is done again for every other player: Update wraps those script functions in Lua.
#include "CoopSize.h"

#include <Windows.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>

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
		SafetyHookMid g_cap, g_cpu, g_allocators, g_gpu;

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
		};

		// The game's Lua is 5.0: varargs come as arg (arg.n), and there's no unpack, so calls are
		// passed on by count (a trailing nil would change what a native sees).
		constexpr const char* MirrorLib = R"(
if not SW_mirror then
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
    if a[1] == "#PLAYER2#" and SW_EXTRA_N then
      local i = 1
      while i <= SW_EXTRA_N do
        local b = { n = a.n }
        local j = 1
        while j <= a.n do b[j] = a[j] j = j + 1 end
        b[1] = SW_EXTRA[i]
        SW_call(f, b)
        i = i + 1
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
	}

	int Players() { return g_players; }

	void Update()
	{
		static DWORD next = 0;
		static std::string last;
		if (g_players == 2 || GetTickCount() < next)
			return;
		next = GetTickCount() + 1000;
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
