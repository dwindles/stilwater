// RimJobsGuard.cpp (Stilwater)
// The Rim Jobs (vehicle customisation) script commands all use the vehicle being customised
// (handle at 0x02528854) without checking it is still alive. If that vehicle is destroyed while
// the menu is open (seen with trainer-spawned cars), commands such as
// vcust_preview_wheel_sizing and vcust_show_nos_hydraulic_warning read through a null pointer.
//
// Each command's entry in the registration code (MOV [ESP+x], function) is pointed at a wrapper
// that runs the original under SEH: an access violation ends the command with no results (nil to
// the script) instead of reaching the crash handler.
#include "RimJobsGuard.h"

#include <Windows.h>
#include <cstdint>
#include <utility>

#include "../FileLogger.h"
#include "../SafeWrite.h"

namespace RimJobsGuard
{
	namespace
	{
		using LuaCFunction = int(__cdecl*)(void* state);

		struct Command
		{
			const char* name;
			uintptr_t function;
			uintptr_t immediate;   // address of the function pointer in the registration code
		};

		// From the registration routine at 0x007BA220.
		constexpr Command Commands[] = {
			{ "vcust_using_lightset",             0x007B81F0, 0x007BA240 },
			{ "vcust_change_top_level_menu",      0x007B8210, 0x007BA250 },
			{ "vcust_select_new_category",        0x007B8350, 0x007BA260 },
			{ "vcust_select_paint_slot",          0x007B83C0, 0x007BA270 },
			{ "vcust_adjust_camera_angle",        0x007B8B60, 0x007BA280 },
			{ "vcust_preview_component",          0x007B8400, 0x007BA290 },
			{ "vcust_preview_wheel_sizing",       0x007B87C0, 0x007BA2A0 },
			{ "vcust_preview_rim_sizing",         0x007B8900, 0x007BA2B0 },
			{ "vcust_preview_color",              0x007B89A0, 0x007BA2C0 },
			{ "vcust_purchase_component",         0x007B8D20, 0x007BA2D0 },
			{ "vcust_purchase_wheels",            0x007B8E00, 0x007BA2E0 },
			{ "vcust_purchase_paint",             0x007B8FA0, 0x007BA2F0 },
			{ "vcust_revert_wheels",              0x007B8B50, 0x007BA300 },
			{ "vcust_revert_wheel_choice",        0x007B8A10, 0x007BA310 },
			{ "vcust_revert_color",               0x007B89E0, 0x007BA326 },
			{ "vcust_show_nos_hydraulic_warning", 0x007B9060, 0x007BA33C },
		};
		constexpr size_t CommandCount = sizeof(Commands) / sizeof(Commands[0]);

		int Filter(unsigned long code)
		{
			return code == EXCEPTION_ACCESS_VIOLATION ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH;
		}

		template <size_t Index>
		int __cdecl Guarded(void* state)
		{
			__try {
				return reinterpret_cast<LuaCFunction>(Commands[Index].function)(state);
			}
			__except (Filter(GetExceptionCode())) {
				Logger::TypedLog(CHN_DEBUG, "Rim Jobs: {} had no vehicle to work on; skipped instead of crashing.\n",
					Commands[Index].name);
				return 0;
			}
		}

		template <size_t... Index>
		void Install(std::index_sequence<Index...>)
		{
			const LuaCFunction wrappers[] = { &Guarded<Index>... };
			for (size_t i = 0; i < CommandCount; i++) {
				// Only patch if the registration code still holds the expected pointer.
				if (*reinterpret_cast<uint32_t*>(Commands[i].immediate) == Commands[i].function)
					SafeWrite32(Commands[i].immediate, reinterpret_cast<uint32_t>(wrappers[i]));
			}
		}
	}

	void Init()
	{
		Install(std::make_index_sequence<CommandCount>{});
	}
}
