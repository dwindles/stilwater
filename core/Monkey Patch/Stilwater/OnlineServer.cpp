// OnlineServer.cpp (Stilwater)
// Patches/OpenSpy.cpp rewrites GameSpy's hostnames in the exe (gpcm.gamespy.com,
// srow2pc.master.gamespy.com, natneg1.gamespy.com, ...) to openspy.net. When [Stilwater]
// OnlineServer names a server, every lookup of an openspy.net or gamespy.com name resolves to that
// server instead, so all of the game's online services go there (the server side is server/ in the
// repo). The game resolves names with WSOCK32 gethostbyname (import ordinal 52, IAT slot 0x00DB8338).
// After signing in, the game asks AuthService for a login certificate: it encrypts the password with
// the RSA key at 0x00DD0C78 (OpenSpy's, from PatchOpenSpy) and checks the reply's signature with it,
// so that key is replaced with the server's (server/webservices.py).
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <cstring>

#include "OnlineServer.h"
#include "../FileLogger.h"
#include "../GameConfig.h"
#include "../SafeWrite.h"

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

	void Init()
	{
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
