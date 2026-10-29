// ClothingTable.cpp (Stilwater)
// The clothing table (customization_items.xtbl) and the stores (customization_stores.xtbl): stores
// hold 512 items instead of 256, a store item the table doesn't have is left out instead of
// crashing the game, and what happens while they load is logged. The game's XML module reports
// problems (a mempool too small, a parse error) through 0x00BFACF0, a printf that goes nowhere on
// PC; those messages are logged here. After the table loads (its loader 0x007BBA50 is called from
// 0x007BF9CE), the number of items loaded (0x025288D8) is logged, and whether each item named in
// [Stilwater] CheckItems (comma separated) was found, looked up the way the stores do (0x00C07160
// on the item name table at 0x02A07900).
#include "ClothingTable.h"

#include <Windows.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <sstream>
#include <string>

#include "../FileLogger.h"
#include "../GameConfig.h"
#include "../SafeWrite.h"
#include <safetyhook.hpp>

namespace ClothingTable
{
	namespace
	{
		SafetyHookMid g_errorHook, g_loadedHook;
		std::string g_check;

		using LookupItem = short(__stdcall*)(void* table, const char* name);
		const auto Lookup = reinterpret_cast<LookupItem>(0x00C07160);
	}

	// Stores hold 256 items in vanilla; every clothing store sells every clothing item (about 500,
	// mods/shared). These are the patches Juiced's DLC support makes for Rusty's Needle's tattoos
	// (DLCSupport.cpp, AppendCustomizationStores), which only happen with a DLC folder: a store is
	// 0x124 bytes and 12 per item (0xD24 for 256), at five places, and the loader stops at 0x007BD62A.
	void RaiseStoreLimit()
	{
		constexpr uint32_t Items = 512, Size = 0x124 + 12 * Items;
		constexpr uintptr_t Sizes[] = { 0x007BD281, 0x007BD2F1, 0x007C4F42, 0x007BFB00, 0x007C4F95 };
		if (*reinterpret_cast<uint32_t*>(0x007BD62A) != 0xFF) {
			Logger::TypedLog(CHN_XTBL, "Clothing table: the store limit was already changed; left as it is.\n");
			return;
		}
		for (uintptr_t at : Sizes)
			if (*reinterpret_cast<uint32_t*>(at) != 0xD24) {
				Logger::TypedLog(CHN_XTBL, "Clothing table: unexpected store size at {:#x}; store limit left at 256.\n", at);
				return;
			}
		SafeWrite32(0x007BD62A, Items - 1);
		for (uintptr_t at : Sizes)
			SafeWrite32(at, Size);
		Logger::TypedLog(CHN_XTBL, "Clothing table: stores hold up to {} items.\n", Items);
	}

	void Init()
	{
		RaiseStoreLimit();
		char check[1024] = {};
		GameConfig::GetStringValue("Stilwater", "CheckItems", "", check,
			"Clothing items to look for after the clothing table loads (comma separated), logged.");
		g_check = check;

		g_errorHook = safetyhook::create_mid(0x00BFACF0, [](SafetyHookContext& ctx) {
			const char* format = *reinterpret_cast<const char**>(ctx.esp + 4);
			char text[512];
			_vsnprintf_s(text, sizeof(text), _TRUNCATE, format, reinterpret_cast<va_list>(ctx.esp + 8));
			Logger::TypedLog(CHN_XTBL, "Game: {}\n", text);
		});

		// Each item the loader takes past the 900th (its name is in EBP before it goes into the name
		// table), the ones it skips as "not ready", and where its loop ends.
		static SafetyHookMid item = safetyhook::create_mid(0x007BBC57, [](SafetyHookContext& ctx) {
			const int count = *reinterpret_cast<int*>(0x025288D8);
			if (count >= 900)
				Logger::TypedLog(CHN_XTBL, "Clothing table: item {} \"{}\"\n", count, ctx.ebp ? reinterpret_cast<const char*>(ctx.ebp) : "(no name)");
		});
		static SafetyHookMid skipped = safetyhook::create_mid(0x007BBB38, [](SafetyHookContext&) {
			const int count = *reinterpret_cast<int*>(0x025288D8);
			if (count >= 900)
				Logger::TypedLog(CHN_XTBL, "Clothing table: skipped a not-ready item at {}\n", count);
		});
		static SafetyHookMid done = safetyhook::create_mid(0x007BCC2F, [](SafetyHookContext&) {
			Logger::TypedLog(CHN_XTBL, "Clothing table: loader finished at {}\n", *reinterpret_cast<int*>(0x025288D8));
		});

		// A store item the item table doesn't have: the game takes the null item and crashes at
		// 0x007BD6F1. Leave it out of the store instead (the store's count, +0x1C, goes back one) and go
		// on with the next (0x007BD8A0; the store loader keeps its loop state on the stack).
		static SafetyHookMid storeItem = safetyhook::create_mid(0x007BD683, [](SafetyHookContext& ctx) {
			if (ctx.eax) return;
			const char* store = *reinterpret_cast<const char**>(ctx.ebx);
			const char* item = "(no name)";
			for (uintptr_t child = *reinterpret_cast<uintptr_t*>(*reinterpret_cast<uintptr_t*>(ctx.esp + 0x24) + 8); child;
				child = *reinterpret_cast<uintptr_t*>(child + 4))
				if (strcmp(*reinterpret_cast<const char**>(child), "Item") == 0) {
					item = *reinterpret_cast<const char**>(child + 0xC);
					break;
				}
			Logger::TypedLog(CHN_XTBL, "Clothing table: store {} lists \"{}\", which isn't loaded; left out.\n", store ? store : "?", item ? item : "?");
			*reinterpret_cast<int*>(ctx.ebx + 0x1C) -= 1;
			ctx.eip = 0x007BD8A0;
		});

		// Saving the player's outfit (the loop at 0x007C33A3, one 0x1C-byte entry per worn item: the
		// item at [ecx-0x14], its chosen style at [ecx-0x10]) reads the style's ID without checking
		// it, and a worn Stilwater shoe once had none: the save crashed at 0x007C33E6. A worn item
		// without a style gets its first one (an item: styles at +0x20, how many at +0x24, ID at +0x14).
		static SafetyHookMid wornStyle = safetyhook::create_mid(0x007C33E3, [](SafetyHookContext& ctx) {
			auto* style = reinterpret_cast<uintptr_t*>(ctx.ecx - 0x10);
			const uintptr_t item = *reinterpret_cast<uintptr_t*>(ctx.ecx - 0x14);
			if (*style || !item || *reinterpret_cast<int*>(item + 0x24) <= 0)
				return;
			*style = *reinterpret_cast<uintptr_t*>(item + 0x20);
			Logger::TypedLog(CHN_XTBL, "Clothing table: worn item {} had no style; saving it with its first.\n",
				*reinterpret_cast<int*>(item + 0x14));
		});

		g_loadedHook = safetyhook::create_mid(0x007BF9D3, [](SafetyHookContext&) {
			Logger::TypedLog(CHN_XTBL, "Clothing table: {} items loaded.\n", *reinterpret_cast<int*>(0x025288D8));
			std::stringstream names(g_check);
			std::string name;
			while (std::getline(names, name, ',')) {
				if (name.empty()) continue;
				const short index = Lookup(reinterpret_cast<void*>(0x02A07900), name.c_str());
				Logger::TypedLog(CHN_XTBL, "Clothing table: \"{}\" {}.\n", name, index >= 0 ? "loaded" : "missing");
			}
		});
	}
}
