// CheatFlag.cpp (Stilwater)
// Saints Row 2 marks the game as cheated with two bytes, 0x02527B5A and 0x02527BE6, which go into
// the save. The cheat-code handler sets them (0x00687E12/18 store 1 from BL; 0x006883DC, 0x006884C8
// and 0x00688603 store 1 outright for particular cheats), and Juiced's teleport, Lua console and the
// trainer set them unless Juiced's DisableCheatFlag patch is on. Stilwater always applies that patch
// whatever juiced.ini says, makes the outright stores write 0, and keeps both bytes clear while
// playing, so a save flagged before loses the flag the next time it's saved.
#include "CheatFlag.h"

#include <Windows.h>
#include <cstdint>

#include "../FileLogger.h"
#include "../SafeWrite.h"
#include "../UGC/Debug.h"

namespace CheatFlag
{
	namespace
	{
		constexpr uintptr_t Flag = 0x02527B5A, SaveFlag = 0x02527BE6;

		// MOV BYTE PTR [flag], 1 (C6 05 <address> 01): the immediate is the instruction's last byte.
		constexpr uintptr_t SetsOne[] = { 0x006883DC, 0x006883E3, 0x006884C8, 0x006884CF, 0x00688603, 0x0068860A };
	}

	void Init()
	{
		if (!Debug::CMPatches_DisableCheatFlag.IsApplied())
			Debug::CMPatches_DisableCheatFlag.Apply();
		int patched = 0;
		for (uintptr_t at : SetsOne) {
			const auto* code = reinterpret_cast<const uint8_t*>(at);
			const uint32_t target = *reinterpret_cast<const uint32_t*>(at + 2);
			if (code[0] == 0xC6 && code[1] == 0x05 && (target == Flag || target == SaveFlag) && code[6] == 1) {
				SafeWrite8(at + 6, 0);
				patched++;
			}
		}
		Logger::TypedLog(CHN_DLL, "CheatFlag: saves are never marked as cheated ({} of {} cheat stores patched).\n",
			patched, sizeof(SetsOne) / sizeof(SetsOne[0]));
	}

	void Update()
	{
		*reinterpret_cast<volatile uint8_t*>(Flag) = 0;
		*reinterpret_cast<volatile uint8_t*>(SaveFlag) = 0;
	}
}
