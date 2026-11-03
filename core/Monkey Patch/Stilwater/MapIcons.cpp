// MapIcons.cpp (Stilwater)
// Map icons at fixed places: the game marks stores and activities but not the interiors you can
// walk into (Club Koi, the Porno Palace, ...). Players add them where they stand (the Insert menu's
// Trainer tab); they're kept in Stilwater\map_icons.txt, one per line: x y z style name.
//
// The game's minimap and pause map icons are records in a list (head at 0x01F91040, circular,
// next at +4) with a type at +0xC and a handle at +0x10 that 0x007A4730 turns into a position each
// frame (types 0-10: an object by handle, a navpoint or trigger by name, ...). It returns "found"
// without a position for types past 10, so ours are type 11 with our own index as the handle, and
// a hook at its type check (0x007A473D) gives our position from the list. They're added with the
// game's own 0x007A1EA0 (type, handle, icon, glow icon, radius, 0), the call minimap_icon_add_*
// makes for the local player, and removed with 0x007A20A0 (type, handle). Twice a second, while a
// save is loaded, any of ours that isn't in the list (a load clears it) is added again.
#include "MapIcons.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "../FileLogger.h"
#include "../General/General.h"
#include <safetyhook.hpp>

namespace MapIcons
{
	namespace
	{
		constexpr int OurType = 11;
		constexpr uintptr_t IconList = 0x01F91040;
		using AddIcon = int(__cdecl*)(int type, int handle, int icon, int glow, float radius, int owner);
		using RemoveIcon = int(__cdecl*)(int type, int handle);
		const auto Add = reinterpret_cast<AddIcon>(0x007A1EA0);
		const auto Remove = reinterpret_cast<RemoveIcon>(0x007A20A0);

		// Icons from the game's list (0x00DD1718): name, icon, glow icon (-1 for none).
		struct Style { const char* name; int icon, glow; };
		constexpr Style Styles[] = {
			{ "Place", 96, 99 },          // map_act_location (and _glow)
			{ "Shop", 16, -1 },           // map_other_hidden_store
			{ "Stairs", 14, -1 },         // map_other_stairs
			{ "Underground", 13, -1 },    // map_other_underground
			{ "Crib", 5, -1 },            // map_other_crib
			{ "Activity", 15, -1 },       // map_other_hidden_act
		};
		constexpr int StyleCount = sizeof(Styles) / sizeof(Styles[0]);

		struct Icon { float pos[3]; int style; std::string name; };
		std::vector<Icon> g_icons;
		int g_style = 0;
		DWORD g_lastCheck = 0;
		SafetyHookMid g_positionHook;

		std::string ListPath()
		{
			char exe[MAX_PATH] = {};
			GetModuleFileNameA(nullptr, exe, MAX_PATH);
			std::string path(exe);
			return path.substr(0, path.find_last_of("\\/") + 1) + "Stilwater\\map_icons.txt";
		}

		void Load()
		{
			g_icons.clear();
			std::ifstream file(ListPath());
			std::string line;
			while (std::getline(file, line)) {
				if (line.empty() || line[0] == '#') continue;
				std::istringstream in(line);
				Icon icon{};
				if (!(in >> icon.pos[0] >> icon.pos[1] >> icon.pos[2] >> icon.style)) continue;
				std::getline(in >> std::ws, icon.name);
				if (icon.style < 0 || icon.style >= StyleCount) icon.style = 0;
				g_icons.push_back(icon);
			}
		}

		void Save()
		{
			std::ofstream file(ListPath(), std::ios::trunc);
			file << "# Stilwater map icons: x y z style name (styles: 0 Place, 1 Shop, 2 Stairs, 3 Underground, 4 Crib, 5 Activity)\n";
			for (const Icon& icon : g_icons) {
				char line[160];
				snprintf(line, sizeof(line), "%.2f %.2f %.2f %d %s\n", icon.pos[0], icon.pos[1], icon.pos[2], icon.style, icon.name.c_str());
				file << line;
			}
		}

		std::set<int> Shown()
		{
			std::set<int> shown;
			const uintptr_t head = *reinterpret_cast<uintptr_t*>(IconList);
			uintptr_t entry = head;
			for (int guard = 0; entry && guard < 4096; guard++) {
				if (*reinterpret_cast<int*>(entry + 0xC) == OurType)
					shown.insert(*reinterpret_cast<int*>(entry + 0x10));
				entry = *reinterpret_cast<uintptr_t*>(entry + 4);
				if (entry == head) break;
			}
			return shown;
		}

		void ClearShown()
		{
			for (int handle : Shown())
				Remove(OurType, handle);
		}

		uintptr_t Player() { return *reinterpret_cast<uintptr_t*>(0x021703D4); }
	}

	void Init()
	{
		Load();
		g_positionHook = safetyhook::create_mid(0x007A473D, [](SafetyHookContext& ctx) {
			const uintptr_t entry = ctx.edi;
			if (*reinterpret_cast<int*>(entry + 0xC) != OurType) return;
			const int index = *reinterpret_cast<int*>(entry + 0x10);
			float* out = reinterpret_cast<float*>(ctx.ebp);
			if (out && index >= 0 && index < (int)g_icons.size()) {
				out[0] = g_icons[index].pos[0];
				out[1] = g_icons[index].pos[1];
				out[2] = g_icons[index].pos[2];
			}
			ctx.eip = 0x007A4AF0;      // the resolver's "found" exit (its registers are pushed already)
		});
		Logger::TypedLog(CHN_DLL, "MapIcons: {} icons from {}.\n", g_icons.size(), ListPath());
	}

	void Update()
	{
		if (*General::GameLoaded != 1 || !Player() || !*reinterpret_cast<uintptr_t*>(IconList)) return;
		const DWORD now = GetTickCount();
		if (now - g_lastCheck < 500) return;
		g_lastCheck = now;
		const std::set<int> shown = Shown();
		for (int i = 0; i < (int)g_icons.size(); i++)
			if (!shown.count(i))
				Add(OurType, i, Styles[g_icons[i].style].icon, Styles[g_icons[i].style].glow, 0.0f, 0);
	}

	std::string StyleName() { return Styles[g_style].name; }
	void CycleStyle(int direction) { g_style = (g_style + direction + StyleCount) % StyleCount; }
	int Count() { return (int)g_icons.size(); }

	void AddHere()
	{
		const uintptr_t me = Player();
		if (!me) return;
		Icon icon{};
		for (int k = 0; k < 3; k++) icon.pos[k] = reinterpret_cast<float*>(me + 0x14)[k];
		icon.style = g_style;
		icon.name = std::string(Styles[g_style].name) + " " + std::to_string(g_icons.size() + 1);
		g_icons.push_back(icon);
		Save();
		g_lastCheck = 0;
	}

	void RemoveNearest()
	{
		const uintptr_t me = Player();
		if (!me || g_icons.empty()) return;
		const float* p = reinterpret_cast<float*>(me + 0x14);
		int nearest = -1;
		float best = 30.0f * 30.0f;
		for (int i = 0; i < (int)g_icons.size(); i++) {
			const float dx = g_icons[i].pos[0] - p[0], dy = g_icons[i].pos[1] - p[1], dz = g_icons[i].pos[2] - p[2];
			const float d = dx * dx + dy * dy + dz * dz;
			if (d < best) { best = d; nearest = i; }
		}
		if (nearest < 0) return;
		// Indices shift: take ours off the map, and the next check puts the rest back.
		ClearShown();
		g_icons.erase(g_icons.begin() + nearest);
		Save();
		g_lastCheck = 0;
	}
}
