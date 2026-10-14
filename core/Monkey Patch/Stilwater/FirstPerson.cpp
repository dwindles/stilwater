// FirstPerson.cpp (Stilwater)
// GTA V-style first-person view, toggled with [Stilwater] FirstPersonKey (default V).
//
// The game's own camera keeps running, so mouse/stick look, aiming and the vehicle chase direction
// behave as usual. Each frame, just before UpdateCamera (0x004932F0) copies the new camera
// position (0x025F5B20) into the current one (0x025F5B14, what rendering and aiming read) at
// 0x004934F0, the new position is moved to the player's eyes. The game's own position is put back
// at the start of the next update, so its camera logic never builds on ours. With the camera
// inside the player, the game's actor fade (run later in the same update) hides the player's body.
//
// Eye position: offsets from the player object's position (+0x14), which is at the feet standing and
// about seat height in a vehicle, along its orientation rows (right, up, forward) at +0x20.
// PageUp/PageDown move the eyes while first person is on; the height is saved per mode.
//
// On foot, [Stilwater] FirstPersonShowBody (default on) keeps the body and weapon visible, like GTA V:
// the actor fade (0x00E8825F) is switched off and the eyes sit a little in front of the face along
// the camera's view direction, so the head is always behind the camera whichever way you look.
#include "FirstPerson.h"

#include <Windows.h>
#include <cmath>
#include <cstring>
#include <string>

#include <safetyhook.hpp>

#include "../GameConfig.h"
#include "../General/General.h"
#include "../UtilsGlobal.h"

// MainHooks.cpp
bool IsKeyPressed(unsigned char Key, bool Hold);
int addsubtitles(const wchar_t* subtitles, float delay, float duration, float whateverthefuck);

namespace FirstPerson
{
	namespace
	{
		struct Vec3 { float x, y, z; };

		Vec3& NewPosition = *reinterpret_cast<Vec3*>(0x025F5B20);
		Vec3& CurrentPosition = *reinterpret_cast<Vec3*>(0x025F5B14);
		const Vec3& NewForward = *reinterpret_cast<const Vec3*>(0x025F5B5C + 0x18); // new orientation, third row
		int& CameraMode = *reinterpret_cast<int*>(0x025F5AE8);      // 0 = normal follow camera
		bool& InCutscene = *reinterpret_cast<bool*>(0x02527D14);
		uint8_t& ActorFade = *reinterpret_cast<uint8_t*>(0x00E8825F); // hides actors the camera is inside

		struct Offsets { float height, forward; const char* key; };
		Offsets OnFoot{ 1.62f, 0.12f, "FirstPersonEyeHeight" };
		Offsets InVehicle{ 0.62f, 0.06f, "FirstPersonVehicleHeight" };
		constexpr float BodyVisibleForward = 0.22f; // clears the face when the body is drawn

		unsigned char g_key = 'V';
		bool g_enabled = false;
		bool g_show_body = true;
		bool g_fade_taken = false;
		uint8_t g_saved_fade = 1;
		bool g_overridden = false;
		Vec3 g_game_position{};
		Vec3 g_eye{};

		SafetyHookMid g_restore_hook;
		SafetyHookMid g_place_hook;

		bool InVehicleNow(uintptr_t player)
		{
			return *reinterpret_cast<int*>(player + 0xD74) > 0;
		}

		bool Active()
		{
			return g_enabled && *General::GameLoaded == 1 && CameraMode == 0 && !InCutscene && UtilsGlobal::getplayer();
		}

		Vec3 Eye(uintptr_t player)
		{
			const float* position = reinterpret_cast<const float*>(player + 0x14);
			const float* rows = reinterpret_cast<const float*>(player + 0x20);   // right, up, forward
			if (InVehicleNow(player)) {
				// Seated: follow the vehicle's full orientation (hills, rolls).
				return {
					position[0] + rows[3] * InVehicle.height + rows[6] * InVehicle.forward,
					position[1] + rows[4] * InVehicle.height + rows[7] * InVehicle.forward,
					position[2] + rows[5] * InVehicle.height + rows[8] * InVehicle.forward,
				};
			}
			// On foot the object only keeps a heading (forward x/z at +0x38/+0x40, which is what
			// noclip writes); its up row isn't set. Characters stand upright, so use world up.
			// With the body drawn, step forward along where the camera looks instead, so the head
			// stays behind the camera when looking sideways.
			float fx = rows[6], fz = rows[8], forward = OnFoot.forward;
			if (g_show_body) {
				const float look = sqrtf(NewForward.x * NewForward.x + NewForward.z * NewForward.z);
				if (look > 0.2f) {
					fx = NewForward.x;
					fz = NewForward.z;
				}
				forward = BodyVisibleForward;
			}
			const float length = sqrtf(fx * fx + fz * fz);
			if (length > 0.0001f) {
				fx /= length;
				fz /= length;
			}
			return {
				position[0] + fx * forward,
				position[1] + OnFoot.height,
				position[2] + fz * forward,
			};
		}

		// Keep the player drawn on foot; give the fade back to the game everywhere else.
		void UpdateBodyFade(bool want_body)
		{
			if (want_body) {
				if (!g_fade_taken) {
					g_saved_fade = ActorFade;
					g_fade_taken = true;
				}
				ActorFade = 0;
			}
			else if (g_fade_taken) {
				ActorFade = g_saved_fade;
				g_fade_taken = false;
			}
		}

		bool Same(const Vec3& a, const Vec3& b)
		{
			return std::memcmp(&a, &b, sizeof(Vec3)) == 0;
		}

		// Start of UpdateCamera: hand the game its own position back.
		void Restore(SafetyHookContext&)
		{
			if (!g_overridden)
				return;
			// Only where ours is still in place (a cutscene or script may have moved the camera since).
			if (Same(CurrentPosition, g_eye))
				CurrentPosition = g_game_position;
			if (Same(NewPosition, g_eye))
				NewPosition = g_game_position;
			g_overridden = false;
		}

		// Just before the new position becomes the current one: move it to the eyes.
		void Place(SafetyHookContext&)
		{
			if (!Active())
				return;
			g_game_position = NewPosition;
			g_eye = Eye(UtilsGlobal::getplayer());
			NewPosition = g_eye;
			g_overridden = true;
		}

		void Say(const std::wstring& text)
		{
			addsubtitles(text.c_str(), 0.0f, 1.5f, 0.0f);
		}
	}

	void Init()
	{
		g_key = (unsigned char)GameConfig::GetValue("Stilwater", "FirstPersonKey", 'V',
			"Key that toggles first person, as a Windows virtual-key code (0x56 = V).");
		OnFoot.height = (float)GameConfig::GetDoubleValue("Stilwater", OnFoot.key, OnFoot.height,
			"First-person eye height above the player's feet, on foot (PageUp/PageDown in game).");
		InVehicle.height = (float)GameConfig::GetDoubleValue("Stilwater", InVehicle.key, InVehicle.height,
			"First-person eye height above the player's seat position, in vehicles (PageUp/PageDown in game).");
		g_show_body = GameConfig::GetValue("Stilwater", "FirstPersonShowBody", 1,
			"Show your body and weapon in first person on foot (1), or hide them (0).") != 0;
		g_restore_hook = safetyhook::create_mid(0x004932F0, Restore);
		g_place_hook = safetyhook::create_mid(0x004934F0, Place);
	}

	void Update()
	{
		uintptr_t player = UtilsGlobal::getplayer();
		if (*General::GameLoaded != 1 || !player) {
			UpdateBodyFade(false);
			return;
		}
		if (IsKeyPressed(g_key, false)) {
			g_enabled = !g_enabled;
			Say(std::wstring(L"First person:[format][color:purple]") + (g_enabled ? L" ON" : L" OFF") + L"[/format]");
		}
		UpdateBodyFade(g_show_body && Active() && !InVehicleNow(player));
		if (!g_enabled)
			return;
		const int step = IsKeyPressed(VK_PRIOR, false) ? 1 : IsKeyPressed(VK_NEXT, false) ? -1 : 0;
		if (step) {
			Offsets& o = InVehicleNow(player) ? InVehicle : OnFoot;
			o.height += 0.05f * step;
			GameConfig::SetDoubleValue("Stilwater", o.key, o.height);
			wchar_t text[64];
			swprintf_s(text, L"Eye height: %.2f m", o.height);
			Say(text);
		}
	}
}
