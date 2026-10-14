// Trainer.cpp (Stilwater)
// In-game cheat menu. Actions run through the game's own mission Lua (General::LuaExecute) or
// Juiced's existing helpers. Text uses the debug font, which has no lowercase glyphs.
#include "Trainer.h"

#include "Horns.h"

#include <Windows.h>
#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

#include "../GameConfig.h"
#include "../General/General.h"
#include "../Render/Render2D.h"
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
		constexpr const char* Player = "\"#PLAYER1#\"";

		struct Vehicle
		{
			std::string internal_name;
			std::string display_name;
		};

		unsigned char g_key = VK_F7;
		bool g_open = false;
		int g_selected = 0;
		bool g_god_mode = false;
		bool g_never_wanted = false;
		int g_hour = 12;
		int g_vehicle = 0;
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
				std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return (char)toupper(c); });
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
			{ [] { return std::string("GIVE $100,000"); },
			  [] { Lua("cash_add(100000)"); } },
			{ [] { return std::string("FULL HEALTH"); },
			  [] { Lua(std::string("set_current_hit_points(") + Player + ", get_max_hit_points(" + Player + "))"); } },
			{ [] { return std::string("GOD MODE: ") + (g_god_mode ? "ON" : "OFF"); },
			  [] {
				  g_god_mode = !g_god_mode;
				  Lua(std::string(g_god_mode ? "turn_invulnerable(" : "turn_vulnerable(") + Player + ")");
			  } },
			{ [] { return std::string("CLEAR WANTED LEVEL"); },
			  [] { Lua("notoriety_reset(\"police\") notoriety_reset(\"Brotherhood\") notoriety_reset(\"Ronin\") notoriety_reset(\"Samedi\")"); } },
			{ [] { return std::string("NEVER WANTED: ") + (g_never_wanted ? "ON" : "OFF"); },
			  [] {
				  g_never_wanted = !g_never_wanted;
				  Lua(g_never_wanted ? "notoriety_reset(\"police\") notoriety_set_max(\"police\", 0)"
					  : "notoriety_set_max(\"police\", 5)");
			  } },
			{ [] {
				  char text[32];
				  snprintf(text, sizeof(text), "TIME: < %02d:00 >", g_hour);
				  return std::string(text);
			  },
			  [] { Lua("set_time_of_day(" + std::to_string(g_hour) + ", 0)"); },
			  [](int direction) {
				  g_hour = (g_hour + direction + 24) % 24;
				  Lua("set_time_of_day(" + std::to_string(g_hour) + ", 0)");
			  } },
			{ [] { return std::string("REPAIR VEHICLE"); },
			  [] { Lua(std::string("local v = get_char_vehicle_name(") + Player + ") if v then vehicle_repair(v, 1.0) end"); } },
			{ [] {
				  if (g_vehicles.empty())
					  return std::string("SPAWN VEHICLE: (NONE LOADED)");
				  return "SPAWN: < " + g_vehicles[g_vehicle].display_name + " >";
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
				  return Horns::InVehicle() ? "HORN: < " + Horns::CurrentName() + " >" : std::string("HORN: (GET IN A VEHICLE)");
			  },
			  [] { Horns::Cycle(1); },
			  [](int direction) { Horns::Cycle(direction); } },
			{ [] { return std::string("TELEPORT TO WAYPOINT"); },
			  [] { TeleportToWaypoint(); } },
			{ [] { return std::string("NOCLIP: ") + (NoclipEnabled ? "ON" : "OFF"); },
			  [] { FlagCheat(); ToggleNoclip(); } },
		};
		constexpr int ItemCount = (int)(sizeof(g_items) / sizeof(g_items[0]));

		void Print(const char* text, int row, int column, int r, int g, int b)
		{
			Render2D::ChangeTextColor(r, g, b, 255);
			__asm pushad
			Render2D::InGamePrint(text, row, Render2D::processtextwidth(column), 6);
			__asm popad
		}
	}

	void Init()
	{
		g_key = (unsigned char)GameConfig::GetValue("Stilwater", "TrainerKey", VK_F7,
			"Key that opens the trainer, as a Windows virtual-key code (0x76 = F7).");
	}

	void Update()
	{
		if (!InSinglePlayer()) {
			g_open = false;
			return;
		}
		Horns::Update();
		if (IsKeyPressed(g_key, false)) {
			g_open = !g_open;
			if (g_open)
				LoadVehicles();
		}
		if (!g_open)
			return;

		if (IsKeyPressed(VK_UP, false))
			g_selected = (g_selected + ItemCount - 1) % ItemCount;
		if (IsKeyPressed(VK_DOWN, false))
			g_selected = (g_selected + 1) % ItemCount;
		if (g_items[g_selected].adjust) {
			if (IsKeyPressed(VK_LEFT, false))
				g_items[g_selected].adjust(-1);
			if (IsKeyPressed(VK_RIGHT, false))
				g_items[g_selected].adjust(1);
		}
		if (IsKeyPressed(VK_RETURN, false))
			g_items[g_selected].activate();
		if (IsKeyPressed(VK_BACK, false))
			g_open = false;
	}

	void Draw()
	{
		if (!g_open)
			return;
		constexpr int column = 40, top = 140, line = 20;
		Print("STILWATER TRAINER", top, column, 139, 92, 246);
		for (int i = 0; i < ItemCount; i++) {
			const bool selected = i == g_selected;
			const std::string text = (selected ? "> " : "  ") + g_items[i].label();
			Print(text.c_str(), top + line * (i + 1), column, selected ? 255 : 200, selected ? 255 : 200, selected ? 255 : 200);
		}
		Print("UP/DOWN SELECT  ENTER USE  LEFT/RIGHT CHANGE  BACKSPACE CLOSE", top + line * (ItemCount + 2), column, 150, 150, 150);
		if (!Debug::CMPatches_DisableCheatFlag.IsApplied())
			Print("USING THE TRAINER FLAGS YOUR SAVE AS CHEATED", top + line * (ItemCount + 3), column, 150, 150, 150);
	}
}
