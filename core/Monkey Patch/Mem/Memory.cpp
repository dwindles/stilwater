// Memory.cpp (uzis)
// --------------------
// Created: 13/12/2024

#include "../FileLogger.h"
#include "../Patcher/patch.h"
#include "../GameConfig.h"
#include <algorithm>
#include <safetyhook.hpp>

namespace Memory
{

	int NewTreeDist = 500000;
	int NewShadowDist = 255;

	void GangstaBrawlMemoryExt()
	{
		Logger::TypedLog(CHN_RL, "Patching GangstaBrawlMemoryExtender to Strong Arm Pools...\n");
		patchBytesM((BYTE*)0x00835879, (BYTE*)"\x6A\x02", 2); // client
		patchBytesM((BYTE*)0x00833A52, (BYTE*)"\x6A\x02", 2); // host
		patchBytesM((BYTE*)0x0082FD84, (BYTE*)"\x83\xC3\x08", 3); // Limit Gangsta Brawl/TGB player cap to 8 from 12.
	}

	void ExpandTreeDist()
	{
		// Increases the Tree Fade Distance from 250000 to 500000
		Logger::TypedLog(CHN_MEMORY, "Increasing Tree Fade Distance to 500000.\n");
		patchFloat((BYTE*)0x0252A058, static_cast<float>(NewTreeDist));
	}

	void ExpandShadowRenderDist()
	{
		// Increases the Shadow Render Distance from 125 to 255, Actually a considerable difference.
		Logger::TypedLog(CHN_MEMORY, "Increasing Shadow Render Distance to 255.\n");
		patchDWord((void*)0x0279778C, NewShadowDist); // Day_ShadowRenderDist > 255
		patchDWord((void*)0x02797790, NewShadowDist); // Night_ShadowRenderDist > 255
		// im a bit scared about these nops but it works?... ~ NOPs calls that set these values from xtbl
		patchNop((BYTE*)0x0054DFEE, 15);
		patchNop((BYTE*)0x0054DFDE, 15);
	}

	// Stilwater: tree and shadow draw distance. See docs/re-notes.md for how these were traced.
	//
	// Trees: each SpeedTree type fades at (type fade distance)^2 * [0x02658E78]. The time-of-day
	// update (0x004D5670) rewrites that multiplier every frame, so it is scaled right after the
	// store at 0x004D57AE. [0x0252A058] is the squared distance used to skip whole tree chunks
	// (chunk drawn if dist^2 <= value * 4); the SpeedTree loader only ever raises it, so it is
	// raised once up front to match.
	static float g_tree_fade_scale = 1.f;

	void ExtendTreeDistance(float scale)
	{
		g_tree_fade_scale = scale * scale; // the game compares squared distances
		patchFloat((BYTE*)0x0252A058, 250000.f * g_tree_fade_scale);
		static SafetyHookMid tree_fade_hook = safetyhook::create_mid(0x004D57B4, [](SafetyHookContext&) {
			*(float*)0x02658E78 *= g_tree_fade_scale;
		});
		Logger::TypedLog(CHN_MEMORY, "Tree draw distance x{:.2f}.\n", scale);
	}

	void StilwaterDistances()
	{
		const float tree = std::clamp((float)GameConfig::GetDoubleValue("Stilwater", "TreeDistance", 1.5,
			"How far trees are drawn, as a multiple of vanilla (1.0 = vanilla, 2.0 = twice as far)."), 1.f, 4.f);
		if (tree > 1.f)
			ExtendTreeDistance(tree);

		const int shadow = (int)GameConfig::GetValue("Stilwater", "ShadowDistance", 255,
			"How far shadows are drawn, in meters (vanilla 125, maximum 255). 0 = vanilla.");
		if (shadow != 0) {
			NewShadowDist = std::clamp(shadow, 32, 255);
			ExpandShadowRenderDist();
		}
	}

	// Stilwater: vehicle streaming slots. Streamed vehicles load into 8 fixed slots (stream setup
	// at 0x0051F700, pool 2): each slot has a 4 MiB region A and a 3 MiB region B, carved from two
	// buffers allocated in 0x0051D800 (32 MiB at 0x02527324, 24 MiB at 0x02527328). A vehicle whose
	// .car_pc + .g_car_pc don't fit in region A never finishes loading, so it silently fails to
	// spawn. The pool keeps the slot sizes it is given, so scaling the buffers and the sizes together
	// is enough.
	static uint32_t g_vehicle_slot_a = 0x400000;

	void ExtendVehicleSlots(double scale)
	{
		constexpr int slots = 8;
		g_vehicle_slot_a = (uint32_t)(0x400000 * scale) & ~0xFFFu;
		const uint32_t slot_b = (uint32_t)(0x300000 * scale) & ~0xFFFu;
		patchInt((void*)0x0051F1A6, g_vehicle_slot_a * slots); // push 0x2000000 (region A buffer)
		patchInt((void*)0x0051F1B3, slot_b * slots);           // push 0x1800000 (region B buffer)
		patchInt((void*)0x0051F876, slot_b);                   // mov [esp+0x54], 0x300000
		// Region A's size comes from ECX, which also sets another pool's slot (0x0051F7D8), so
		// overwrite only the vehicle pool's copy once it is stored.
		static SafetyHookMid slot_a_hook = safetyhook::create_mid(0x0051F7E0, [](SafetyHookContext& ctx) {
			*(uint32_t*)(ctx.esp + 0x4C) = g_vehicle_slot_a;
		});
		Logger::TypedLog(CHN_MEMORY, "Vehicle stream slots: {} KB + {} KB.\n", g_vehicle_slot_a / 1024, slot_b / 1024);
	}

	struct myLogoItem
	{
		char bytes[24];
	};

#define MAX_CUSTOM_LOGOS   24
	myLogoItem NEW_LOGOS[MAX_CUSTOM_LOGOS];


	void PatchLogos() {
		patchDWord((BYTE*)0x007BD198, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007BDF4A, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007BE426, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007BF99E, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C029D, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C02AE, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C02B9, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C10E9, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C10FA, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C1105, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C2BFB, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C3665, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C38B4, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C40E9, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C40F4, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C40FF, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C410A, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C4C97, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C52A5, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C58D4, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C58E5, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C58F0, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C5919, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C592A, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C5935, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C5972, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C9FE0, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C9FF1, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007C9FFC, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007CB03C, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007CB04D, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007CB05A, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007CC022, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007CC063, (int)&NEW_LOGOS);
		patchDWord((BYTE*)0x007CCE6F, (int)&NEW_LOGOS);

	}
	void Init()
	{
		// ~ PatchLogos();
#if RELOADED
		if (GameConfig::GetValue("Debug", "GangstaBrawlMemoryExtender", 1)) // Replaces GB MemLimits with SA.
		{
			GangstaBrawlMemoryExt();
		}
#endif
#if !JLITE

	int perm_mesh_cpu_new_size = std::clamp((int)GameConfig::GetValue("Mempool", "perm_mesh_cpu", 1114112  * 2, "Default 1114112"), 1114112,INT32_MAX / 4);

			patchInt((void*)(0x0051DED7 + 1), perm_mesh_cpu_new_size);
			patchInt((void*)(0x0051DF0F + 1), perm_mesh_cpu_new_size);
			if(perm_mesh_cpu_new_size != 1114112)
			Logger::TypedLog(CHN_DEBUG, "Expanded perm mesh cpu to {}\n", perm_mesh_cpu_new_size);

	int audio_wavebank_new_size = std::clamp((int)GameConfig::GetValue("Mempool", "audio_wavebank", 102760448, "Default 102760448"), 102760448, INT32_MAX / 4);
			if (audio_wavebank_new_size != 102760448) {
				patchInt((void*)(0x0051EBD7 + 1), audio_wavebank_new_size);
				patchInt((void*)(0x0051EC19 + 1), audio_wavebank_new_size);

				Logger::TypedLog(CHN_DEBUG, "Expanded audio - wavebank to {}\n", audio_wavebank_new_size);

			}

	int animation_new_size = std::clamp((int)GameConfig::GetValue("Mempool", "animation", 17293312 * 2, "Default 17293312"), 17293312, INT32_MAX / 4);
			if (animation_new_size != 17293312) {
				patchInt((void*)(0x51FB30 + 1), animation_new_size);
				Logger::TypedLog(CHN_DEBUG, "Expanded animation to {}\n", animation_new_size);

			}

		//if (GameConfig::GetValue("Graphics", "ExtendedTreeFadeDistance", 0))
		//{
		//	ExpandTreeDist();
		//}

		//if (GameConfig::GetValue("Graphics", "ExtendedShadowRenderDistance", 0))
		//{
		//	ExpandShadowRenderDist();
		//}

		StilwaterDistances();

		const double vehicle_memory = std::clamp(GameConfig::GetDoubleValue("Stilwater", "VehicleMemoryScale", 2.0,
			"Size of each streamed vehicle's memory slot, as a multiple of vanilla (4 MB model + 3 MB textures). Needed for high-detail car mods."), 1.0, 4.0);
		if (vehicle_memory > 1.0)
			ExtendVehicleSlots(vehicle_memory);
#endif
	}
}
