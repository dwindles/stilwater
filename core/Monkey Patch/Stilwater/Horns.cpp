// Horns.cpp (Stilwater)
// Each vehicle model's horn is a u16 index at +0x540 of its vehicle table entry (2000 bytes, set
// from the model's <Horn>), which a car object points to at +0x84E4. The game reads it every time
// the horn sounds (0x00B40B60), so changing it takes effect immediately. The horn table (from
// foley_horns.xtbl, read at 0x004883E0) is *(0x00F53078): 8 bytes per horn, the game string hash
// of its name (0x00BDCB30: CRC table 0x00E843B8, lower case) and its u16 sound id; the count is a
// u16 at 0x02526B6C.
#include "Horns.h"

#include <Windows.h>
#include <cctype>
#include <cstdint>
#include <cstdio>

#include "../GameConfig.h"
#include "../UtilsGlobal.h"

namespace Horns
{
	namespace
	{
		constexpr const char* Section = "StilwaterHorns";

		// SR2's horns (foley_horns.xtbl) and how the menu shows them.
		struct Known { const char* name; const char* label; };
		constexpr Known KnownHorns[] = {
			{ "Default", "DEFAULT" }, { "Exotic_1", "SPORTS 1" }, { "Exotic_2", "SPORTS 2" },
			{ "Luxury_1", "LUXURY 1" }, { "Luxury_2", "LUXURY 2" }, { "Luxury_3", "LUXURY 3" },
			{ "Compact_1", "COMPACT 1" }, { "Compact_2", "COMPACT 2" },
			{ "Oldschool_1", "OLD SCHOOL 1" }, { "Oldschool_2", "OLD SCHOOL 2" },
			{ "Semi_1", "SEMI TRUCK 1" }, { "Semi_2", "SEMI TRUCK 2" },
			{ "Truck_1", "PICKUP 1" }, { "Truck_2", "PICKUP 2" },
			{ "EL_TRAIN", "TRAIN" }, { "Yacht_1", "YACHT 1" }, { "Yacht_2", "YACHT 2" },
		};

		uint32_t GameHash(const char* text)
		{
			const uint32_t* table = reinterpret_cast<const uint32_t*>(0x00E843B8);
			uint32_t h = 0;
			for (; *text; ++text)
				h = (h >> 8) ^ table[(static_cast<uint32_t>(std::tolower(static_cast<unsigned char>(*text))) ^ h) & 0xFF];
			return h;
		}

		int Count()
		{
			return *reinterpret_cast<uint16_t*>(0x02526B6C);
		}

		uint32_t HashAt(int index)
		{
			auto table = *reinterpret_cast<const uint8_t**>(0x00F53078);
			return table ? *reinterpret_cast<const uint32_t*>(table + 8 * index) : 0;
		}

		const Known* KnownAt(int index)
		{
			const uint32_t h = HashAt(index);
			for (const Known& k : KnownHorns)
				if (GameHash(k.name) == h)
					return &k;
			return nullptr;
		}

		int IndexOf(const char* name)
		{
			const uint32_t h = GameHash(name);
			for (int i = 0; i < Count(); i++)
				if (HashAt(i) == h)
					return i;
			return -1;
		}

		// The player's vehicle's table entry, or 0.
		uintptr_t VehicleEntry()
		{
			const uintptr_t player = UtilsGlobal::getplayer();
			if (!player)
				return 0;
			const int handle = *reinterpret_cast<int*>(player + 0xD74);
			if (handle <= 0)
				return 0;
			const uintptr_t object = *reinterpret_cast<uintptr_t*>(0x02149C64 + ((handle & 0xFFF) << 4));
			if (!object || *reinterpret_cast<int*>(object + 0x44) != handle)
				return 0;
			const uintptr_t entry = *reinterpret_cast<uintptr_t*>(object + 0x84E4);
			const uintptr_t table = *reinterpret_cast<uintptr_t*>(0x004840C7);   // Juiced's vehicle table
			const int models = *reinterpret_cast<int*>(0x0252A0D8);
			if (entry < table || entry >= table + 2000u * models || (entry - table) % 2000)
				return 0;
			return entry;
		}

		uint16_t& HornOf(uintptr_t entry) { return *reinterpret_cast<uint16_t*>(entry + 0x540); }
		const char* ModelOf(uintptr_t entry) { return reinterpret_cast<const char*>(entry + 0x80); }

		uintptr_t g_last_entry = 0;
	}

	bool InVehicle()
	{
		return VehicleEntry() && Count() > 0;
	}

	std::string CurrentName()
	{
		const uintptr_t entry = VehicleEntry();
		if (!entry || Count() <= 0)
			return "";
		const int index = HornOf(entry);
		if (index >= Count())
			return "NONE";
		if (const Known* k = KnownAt(index))
			return k->label;
		char text[16];
		snprintf(text, sizeof(text), "HORN %d", index + 1);
		return text;
	}

	void Cycle(int direction)
	{
		const uintptr_t entry = VehicleEntry();
		const int count = Count();
		if (!entry || count <= 0)
			return;
		int index = HornOf(entry) < count ? HornOf(entry) : 0;
		index = (index + direction + count) % count;
		HornOf(entry) = static_cast<uint16_t>(index);
		if (const Known* k = KnownAt(index))
			GameConfig::SetStringValue(Section, ModelOf(entry), k->name);
	}

	void Update()
	{
		// Reapply a saved choice once each time the player gets into a different model.
		const uintptr_t entry = VehicleEntry();
		if (entry == g_last_entry)
			return;
		g_last_entry = entry;
		if (!entry)
			return;
		char saved[64] = {};
		GetPrivateProfileStringA(Section, ModelOf(entry), "", saved, sizeof(saved), GameConfig::GetINIPath());
		if (!saved[0])
			return;
		const int index = IndexOf(saved);
		if (index >= 0)
			HornOf(entry) = static_cast<uint16_t>(index);
	}
}
