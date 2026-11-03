// Trainer.cpp (Stilwater)
// The cheats on the Insert menu's Trainer tab (InviteMenu.cpp draws them). Actions run through the
// game's own mission Lua (General::LuaExecute) or Juiced's existing helpers.
#include "Trainer.h"

#include "Horns.h"
#include "ExtraPlayers.h"
#include "MapIcons.h"

#include <Windows.h>
#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

#include "../GameConfig.h"
#include "../General/General.h"
#include "../UGC/Debug.h"
#include "../UtilsGlobal.h"

// MainHooks.cpp
bool IsKeyPressed(unsigned char Key, bool Hold);
void VehicleSpawner(const char* Name, const char* Var);
void TeleportToWaypoint();
void ToggleNoclip();
extern bool NoclipEnabled;

namespace Trainer
{
	namespace
	{
		// This PC's player: #PLAYER1# for the host, #PLAYER2# for whoever joined their co-op game.
		constexpr const char* Player = "(LOCAL_PLAYER or \"#PLAYER1#\")";

		struct Vehicle
		{
			std::string internal_name;
			std::string display_name;
		};

		bool g_god_mode = false;
		bool g_never_wanted = false;
		bool g_no_busted = false, g_peds = true, g_traffic = true, g_cops = true, g_gangs = true;
		int g_wanted = 0;
		int g_hour = 12;
		int g_vehicle = 0;

		// The switches are kept in juiced.ini [StilwaterTrainer] and come back on every launch, applied
		// once each time a save has loaded (g_applied).
		constexpr const char* Saved = "StilwaterTrainer";
		bool g_applied = false;

		void Remember()
		{
			GameConfig::SetValue(Saved, "GodMode", g_god_mode);
			GameConfig::SetValue(Saved, "NeverWanted", g_never_wanted);
			GameConfig::SetValue(Saved, "CantBeArrested", g_no_busted);
			GameConfig::SetValue(Saved, "Pedestrians", g_peds);
			GameConfig::SetValue(Saved, "Traffic", g_traffic);
			GameConfig::SetValue(Saved, "PolicePatrols", g_cops);
			GameConfig::SetValue(Saved, "GangPatrols", g_gangs);
			GameConfig::SetValue(Saved, "ShowMyNameTag", ExtraPlayers::OwnTag());
		}
		std::vector<Vehicle> g_vehicles;

		bool InSinglePlayer()
		{
			return *General::GameLoaded == 1 && *General::LobbyCheck != 0 && *General::CurrentGamemode == -1
				&& UtilsGlobal::getplayer();
		}

		// Same flagging Juiced's teleport uses, unless the player turned the cheat flag off.
		void FlagCheat()
		{
			if (!Debug::CMPatches_DisableCheatFlag.IsApplied()) {
				*(BYTE*)0x02527B5A = 1;
				*(BYTE*)0x02527BE6 = 1;
			}
		}

		void Lua(const std::string& command)
		{
			FlagCheat();
			General::LuaExecute(command.c_str());
		}

		// The game's vehicle table, read the same way as Juiced's vehicle spawner.
		void LoadVehicles()
		{
			if (!g_vehicles.empty())
				return;
			for (int i = 0; i < *(int*)0x252A0D8; i++) {
				auto entry = (*(uintptr_t*)0x004840C7) + 2000 * i;
				auto display = (wchar_t*)(entry + 0x22E);
				int len = WideCharToMultiByte(CP_UTF8, 0, display, -1, nullptr, 0, nullptr, nullptr);
				std::string name(len > 0 ? len - 1 : 0, '\0');
				WideCharToMultiByte(CP_UTF8, 0, display, -1, name.data(), len, nullptr, nullptr);
				if (!name.empty())
					g_vehicles.push_back({ (char*)(entry + 0x80), name });
			}
			std::sort(g_vehicles.begin(), g_vehicles.end(),
				[](const Vehicle& a, const Vehicle& b) { return a.display_name < b.display_name; });
		}

		struct Item
		{
			std::string (*label)();
			void (*activate)();
			void (*adjust)(int direction) = nullptr;
		};

		const Item g_items[] = {
			{ [] { return std::string("Give $100,000"); },
			  [] { Lua("cash_add(100000)"); } },
			{ [] { return std::string("Full health"); },
			  [] { Lua(std::string("set_current_hit_points(") + Player + ", get_max_hit_points(" + Player + "))"); } },
			{ [] { return std::string("God mode\t") + (g_god_mode ? "On" : "Off"); },
			  [] {
				  g_god_mode = !g_god_mode;
				  Remember();
				  Lua(std::string(g_god_mode ? "turn_invulnerable(" : "turn_vulnerable(") + Player + ")");
			  } },
			{ [] { return std::string("Clear wanted level"); },
			  [] { Lua("notoriety_reset(\"police\") notoriety_reset(\"Brotherhood\") notoriety_reset(\"Ronin\") notoriety_reset(\"Samedi\")"); } },
			{ [] { return std::string("Never wanted\t") + (g_never_wanted ? "On" : "Off"); },
			  [] {
				  g_never_wanted = !g_never_wanted;
				  Remember();
				  Lua(g_never_wanted ? "notoriety_reset(\"police\") notoriety_set_max(\"police\", 0)"
					  : "notoriety_set_max(\"police\", 5)");
			  } },
			{ [] {
				  char text[32];
				  snprintf(text, sizeof(text), "Time of day\t%02d:00", g_hour);
				  return std::string(text);
			  },
			  [] { Lua("set_time_of_day(" + std::to_string(g_hour) + ", 0)"); },
			  [](int direction) {
				  g_hour = (g_hour + direction + 24) % 24;
				  Lua("set_time_of_day(" + std::to_string(g_hour) + ", 0)");
			  } },
			{ [] { return std::string("Repair vehicle"); },
			  [] { Lua(std::string("local v = get_char_vehicle_name(") + Player + ") if v then vehicle_repair(v, 1.0) end"); } },
			{ [] {
				  if (g_vehicles.empty())
					  return std::string("Spawn vehicle\tNone loaded");
				  return "Spawn vehicle\t" + g_vehicles[g_vehicle].display_name;
			  },
			  [] {
				  if (g_vehicles.empty())
					  return;
				  FlagCheat();
				  VehicleSpawner(g_vehicles[g_vehicle].internal_name.c_str(), "-1");
			  },
			  [](int direction) {
				  if (!g_vehicles.empty())
					  g_vehicle = (g_vehicle + direction + (int)g_vehicles.size()) % (int)g_vehicles.size();
			  } },
			{ [] {
				  return Horns::InVehicle() ? "Horn\t" + Horns::CurrentName() : std::string("Horn\tGet in a vehicle");
			  },
			  [] { Horns::Cycle(1); },
			  [](int direction) { Horns::Cycle(direction); } },
			{ [] { return std::string("Teleport to waypoint"); },
			  [] { TeleportToWaypoint(); } },
			{ [] { return std::string("Noclip\t") + (NoclipEnabled ? "On" : "Off"); },
			  [] { FlagCheat(); ToggleNoclip(); } },
			{ [] { return "Wanted level\t" + std::to_string(g_wanted) + (g_wanted == 1 ? " star" : " stars"); },
			  [] { Lua("notoriety_set(\"police\", " + std::to_string(g_wanted) + ")"); },
			  [](int direction) {
				  g_wanted = std::clamp(g_wanted + direction, 0, 5);
				  Lua("notoriety_set(\"police\", " + std::to_string(g_wanted) + ")");
			  } },
			{ [] { return std::string("Can't be arrested\t") + (g_no_busted ? "On" : "Off"); },
			  [] {
				  g_no_busted = !g_no_busted;
				  Remember();
				  Lua(std::string("set_player_can_be_busted(") + Player + (g_no_busted ? ", false)" : ", true)"));
			  } },
			{ [] { return std::string("Pedestrians\t") + (g_peds ? "On" : "Off"); },
			  [] { g_peds = !g_peds; Remember(); Lua(std::string("spawning_pedestrians(") + (g_peds ? "true" : "false") + ")"); } },
			{ [] { return std::string("Traffic\t") + (g_traffic ? "On" : "Off"); },
			  [] { g_traffic = !g_traffic; Remember(); Lua(std::string("spawning_vehicles(") + (g_traffic ? "true" : "false") + ")"); } },
			{ [] { return std::string("Police patrols\t") + (g_cops ? "On" : "Off"); },
			  [] { g_cops = !g_cops; Remember(); Lua(std::string("spawning_allow_cop_ambient_spawns(") + (g_cops ? "true" : "false") + ")"); } },
			{ [] { return std::string("Gang patrols\t") + (g_gangs ? "On" : "Off"); },
			  [] { g_gangs = !g_gangs; Remember(); Lua(std::string("spawning_allow_gang_ambient_spawns(") + (g_gangs ? "true" : "false") + ")"); } },
			// Co-op past two players (ExtraPlayers.cpp): who's in the world (clicking leaves a friend's
			// world), and a friend's character that copies you 3 s late, to try it alone.
			{ [] { return "World\t" + ExtraPlayers::Status(); },
			  [] { ExtraPlayers::Leave(); } },
			{ [] { return std::string("Test friend character\t") + (ExtraPlayers::Ghost() ? "On" : "Off"); },
			  [] { ExtraPlayers::SetGhost(!ExtraPlayers::Ghost()); } },
			{ [] { return std::string("Show my name tag\t") + (ExtraPlayers::OwnTag() ? "On" : "Off"); },
			  [] { ExtraPlayers::SetOwnTag(!ExtraPlayers::OwnTag()); Remember(); } },
			// Map icons of our own (MapIcons.cpp): one where you stand, in the style picked with left/right.
			{ [] { return "Add map icon here\t" + MapIcons::StyleName(); },
			  [] { MapIcons::AddHere(); },
			  [](int direction) { MapIcons::CycleStyle(direction); } },
			{ [] { return "Remove nearest map icon\t" + std::to_string(MapIcons::Count()) + " placed"; },
			  [] { MapIcons::RemoveNearest(); } },
		};
		constexpr int ItemCount = (int)(sizeof(g_items) / sizeof(g_items[0]));
	}

	void Init()
	{
		g_god_mode = GameConfig::GetValue(Saved, "GodMode", 0, "The Insert menu's trainer switches, as you left them (1 = on).") != 0;
		g_never_wanted = GameConfig::GetValue(Saved, "NeverWanted", 0) != 0;
		g_no_busted = GameConfig::GetValue(Saved, "CantBeArrested", 0) != 0;
		g_peds = GameConfig::GetValue(Saved, "Pedestrians", 1) != 0;
		g_traffic = GameConfig::GetValue(Saved, "Traffic", 1) != 0;
		g_cops = GameConfig::GetValue(Saved, "PolicePatrols", 1) != 0;
		g_gangs = GameConfig::GetValue(Saved, "GangPatrols", 1) != 0;
		ExtraPlayers::SetOwnTag(GameConfig::GetValue(Saved, "ShowMyNameTag", 0) != 0);
	}

	void Update()
	{
		if (!InSinglePlayer()) {
			g_applied = false;
			return;
		}
		Horns::Update();
		// The switches left off their default, once a save has loaded.
		if (!g_applied) {
			g_applied = true;
			if (g_no_busted) Lua(std::string("set_player_can_be_busted(") + Player + ", false)");
			if (!g_peds) Lua("spawning_pedestrians(false)");
			if (!g_traffic) Lua("spawning_vehicles(false)");
			if (!g_cops) Lua("spawning_allow_cop_ambient_spawns(false)");
			if (!g_gangs) Lua("spawning_allow_gang_ambient_spawns(false)");
		}
		// Missions, cutscenes and dying turn invulnerability and the wanted cap back off, so the
		// switches are applied again every couple of seconds while they're on.
		static DWORD last = 0;
		if (GetTickCount() - last < 2000)
			return;
		last = GetTickCount();
		if (g_god_mode)
			General::LuaExecute((std::string("turn_invulnerable(") + Player + ")").c_str());
		if (g_never_wanted)
			General::LuaExecute("notoriety_reset(\"police\") notoriety_set_max(\"police\", 0)");
	}

	// --- the game's own cheats (cheats.xtbl, the phone's cheat list): entries of 0x68 bytes from
	// 0x027A6A68, as many as 0x02527B5C. +0 a cheat that stays on (+1 says whether it is), +3 not
	// allowed in co-op, +0xC its name. 0x006862F0 turns one on and 0x006863C0 off (ESI = the entry),
	// as the game's console commands do.
	namespace
	{
		constexpr uintptr_t CheatTable = 0x027A6A68, CheatStride = 0x68;

		uint8_t* Cheat(int index) { return reinterpret_cast<uint8_t*>(CheatTable + index * CheatStride); }

		void CheatOn(uint8_t* entry)
		{
			__asm {
				push esi
				mov esi, entry
				push 1
				mov eax, 0x006862F0
				call eax
				pop esi
			}
		}

		void CheatOff(uint8_t* entry)
		{
			__asm {
				push esi
				mov esi, entry
				push 0
				push 1
				mov eax, 0x006863C0
				call eax
				pop esi
			}
		}
	}

	int CheatCount()
	{
		const int count = *reinterpret_cast<int*>(0x02527B5C);
		return count > 0 && count < 256 ? count : 0;
	}

	std::string CheatLabel(int index)
	{
		const uint8_t* entry = Cheat(index);
		const auto* name = *reinterpret_cast<const wchar_t* const*>(entry + 0xC);
		std::string label = "Cheat";
		if (name) {
			int size = WideCharToMultiByte(CP_UTF8, 0, name, -1, nullptr, 0, nullptr, nullptr);
			label.assign(size > 0 ? size - 1 : 0, '\0');
			WideCharToMultiByte(CP_UTF8, 0, name, -1, label.data(), size, nullptr, nullptr);
		}
		if (entry[0]) label += entry[1] ? "\tOn" : "\tOff";
		return label;
	}

	// Returns why it couldn't, or "".
	std::string CheatActivate(int index)
	{
		if (!InSinglePlayer() || index < 0 || index >= CheatCount()) return "";
		uint8_t* entry = Cheat(index);
		if (entry[3] && *reinterpret_cast<uint8_t*>(0x02527B5B))
			return "That cheat doesn't work in co-op.";
		if (entry[0] && entry[1]) CheatOff(entry);
		else CheatOn(entry);
		return "";
	}

	void Opened()
	{
		LoadVehicles();
	}

	int Count() { return ItemCount; }
	std::string Label(int item) { return g_items[item].label(); }
	bool CanAdjust(int item) { return g_items[item].adjust != nullptr; }

	void Activate(int item)
	{
		if (InSinglePlayer())
			g_items[item].activate();
	}

	void Adjust(int item, int direction)
	{
		if (InSinglePlayer() && g_items[item].adjust)
			g_items[item].adjust(direction);
	}
}
