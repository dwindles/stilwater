// OnlineServer.cpp (Stilwater)
// Patches/OpenSpy.cpp rewrites GameSpy's hostnames in the exe (gpcm.gamespy.com,
// srow2pc.master.gamespy.com, natneg1.gamespy.com, ...) to openspy.net. When [Stilwater]
// OnlineServer names a server, every lookup of an openspy.net or gamespy.com name resolves to that
// server instead, so all of the game's online services go there (the server side is server/ in the
// repo). The game resolves names with WSOCK32 gethostbyname (import ordinal 52, IAT slot 0x00DB8338).
// After signing in, the game asks AuthService for a login certificate: it encrypts the password with
// the RSA key at 0x00DD0C78 (OpenSpy's, from PatchOpenSpy) and checks the reply's signature with it,
// so that key is replaced with the server's (server/webservices.py).
//
// Signing in by itself: the game keeps the sign-in fields in settings.dat (read at start into
// 0x0212AC08 e-mail, 0x0212ABC8 password, 0x0212AB48 name; the launcher writes them) but still asks
// every run: on PC, Co-op > Online shows the sign-in box whenever the online state 0x02529334 isn't
// 4 (is_connected_to_network and is_connected_to_service both just test that). States: 0 off or
// service down, 1 checking the service, 2 ready (also after a failed sign-in, error in 0x02529338),
// 3 signing in (20 s timeout), 4 signed in; 0x02529331 is set once the online layer has started
// (0x008CCD60, at game start). With a saved login, once the layer is up the game is signed in the
// way the box's "Log into" does it (try_and_login_to_gamespy 0x007EE490 -> 0x008CD260), quietly:
// the login step's "Logging in..." box (0x00753650, called at 0x008CF584) is skipped and the result
// boxes are turned off (0x0212A5EB, which the online pump 0x008CCEB0 checks). Pressing "Log into"
// while that is still going adopts it: the box and the result show as if the menu had started it.
// If it fails, once more after 30 s, then the box as before. [Stilwater] AutoSignIn=0 turns it off.
// (The online layer's own log, 0x008CBF50: states, errors, NAT negotiation, is already in debug.txt
// as [INTERNAL] "GAMESPY: n] CORE: ..." lines, from UGC/InternalPrint.cpp.)
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <cstring>

#include "OnlineServer.h"
#include "../FileLogger.h"
#include "../GameConfig.h"
#include "../SafeWrite.h"
#include <safetyhook.hpp>

namespace OnlineServer
{
	namespace
	{
		constexpr UInt32 GetHostByNameSlot = 0x00DB8338;
		constexpr UInt32 AuthServiceKey = 0x00DD0C78;
		constexpr char DefaultServer[] = "155.138.222.253";
		// Public half of Stilwater Online's AuthService key (/etc/stilwater-online/authservice.pem;
		// server/deploy.sh prints it). Same length as the key it replaces: 256 hex digits.
		constexpr char ServerKey[] =
			"c961cff1260ab59388cb66710a2a1c502d2e60545ac4adcba7772290cd0077b282851fd20137e9ac5d2b7af96ed8d918"
			"e2a8dd5d955823621abeeea123fdb78b742003291cfdc77c50d149d715c61d90d74848a6fc468085dbc351bd3e965fdb"
			"0294e525020406933191d5248640a7ab22561ff9ad8b7ef3a8249ee1fd639a55";
		static_assert(sizeof(ServerKey) == 257, "AuthService key must be 1024 bits");

		using GetHostByName = hostent* (WINAPI*)(const char*);
		GetHostByName Original = nullptr;
		char Server[MAX_PATH] = {};

		bool EndsWith(const char* text, const char* suffix)
		{
			const size_t length = strlen(text), suffixLength = strlen(suffix);
			return length >= suffixLength && _stricmp(text + length - suffixLength, suffix) == 0;
		}

		bool IsGameSpyName(const char* name)
		{
			return EndsWith(name, ".openspy.net") || _stricmp(name, "openspy.net") == 0 ||
				EndsWith(name, ".gamespy.com") || _stricmp(name, "gamespy.com") == 0;
		}

		hostent* WINAPI Resolve(const char* name)
		{
			if (name && IsGameSpyName(name))
			{
				Logger::TypedLog(CHN_NET, "OnlineServer: {} -> {}\n", name, Server);
				return Original(Server);
			}
			return Original(name);
		}
	}

	namespace
	{
		auto& Started = *reinterpret_cast<volatile char*>(0x02529331);
		auto& State = *reinterpret_cast<volatile int*>(0x02529334);
		auto& ShowResult = *reinterpret_cast<volatile char*>(0x0212A5EB);
		const char* const Email = reinterpret_cast<const char*>(0x0212AC08);
		const char* const Password = reinterpret_cast<const char*>(0x0212ABC8);
		const char* const Name = reinterpret_cast<const char*>(0x0212AB48);

		bool g_autoSignIn = true;
		bool g_signingIn = false;   // inside our call to 0x008CD260
		bool g_quiet = false;       // our sign-in is still going and nobody is shown it
		SafetyHookMid g_loggingInBox, g_logInPressed;

		void OpenLoggingInBox() { reinterpret_cast<void(__cdecl*)()>(0x00753650)(); }
	}

	void Update()
	{
		static const DWORD started = GetTickCount();
		static DWORD wait = 5000;
		static int tries = 0;
		if (g_quiet && State != 3)
			g_quiet = false;              // signed in or failed, without a word
		if (!g_autoSignIn || tries >= 2)
			return;
		if (State == 4) {
			tries = 2;                    // signed in (by us or by hand): nothing more to do
			return;
		}
		// From 2 only: the service answered and the modules are set up (0x008CCB20). In 0 (the service
		// didn't answer) "Log into" would connect modules that were never set up.
		const DWORD elapsed = GetTickCount() - started;
		if (elapsed < wait || !Started || State != 2 || !*Email || !*Password)
			return;
		tries++;
		wait = elapsed + 30000;
		Logger::TypedLog(CHN_NET, "OnlineServer: signing in as {} with the saved login.\n", Name);
		g_signingIn = true;
		reinterpret_cast<int(__cdecl*)()>(0x008CD260)();
		g_signingIn = false;
		ShowResult = 0;
		g_quiet = State == 3;
	}

	void Init()
	{
		g_autoSignIn = GameConfig::GetValue("Stilwater", "AutoSignIn", 1,
			"Sign in to online co-op with the saved login when the game starts (0 = ask every time).") != 0;
		// The login step opens "Logging in..." with a Cancel button; not for our quiet sign-in.
		g_loggingInBox = safetyhook::create_mid(0x008CF584, [](SafetyHookContext& ctx) {
			if (g_signingIn)
				ctx.eip = 0x008CF589;
		});
		// "Log into" while our sign-in is still going: show it from here as the menu would have.
		g_logInPressed = safetyhook::create_mid(0x007EE490, [](SafetyHookContext&) {
			if (g_quiet && State == 3) {
				g_quiet = false;
				OpenLoggingInBox();
				ShowResult = 1;
			}
		});
		GameConfig::GetStringValue("Stilwater", "OnlineServer", DefaultServer, Server,
			"Where online co-op connects: Stilwater Online's address, or openspy for OpenSpy.");
		if (!*Server || _stricmp(Server, "openspy") == 0)
		{
			Logger::TypedLog(CHN_DLL, "OnlineServer: using OpenSpy.\n");
			return;
		}
		Original = *reinterpret_cast<GetHostByName*>(GetHostByNameSlot);
		SafeWrite32(GetHostByNameSlot, reinterpret_cast<UInt32>(&Resolve));
		SafeWriteBuf(AuthServiceKey, const_cast<char*>(ServerKey), sizeof(ServerKey));
		Logger::TypedLog(CHN_DLL, "OnlineServer: online services go to {}.\n", Server);
	}
}
