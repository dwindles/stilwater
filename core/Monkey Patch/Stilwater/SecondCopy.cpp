// SecondCopy.cpp (Stilwater)
// More copies of the game on the same PC (up to 4), so co-op past two players can be tried with one
// friend or none: the launcher's --second-copy / --third-copy / --fourth-copy start the game with
// STILWATER_COPY=2..4 (and prepare its save folder, launcher/SecondCopy.cs). Such a copy:
//  - starts although another is running: the game makes a mutex and quits if it exists
//    (0x00BFA620; its jne at 0x00BFA6B6 becomes a jmp),
//  - keeps its saves, settings.dat (its own sign-in) and controls in "Second copy" (and so on) under
//    the game's save folder (%LOCALAPPDATA%\THQ\Saints Row 2, built by WinMain 0x00520BA0 into
//    0x0144E650),
//  - has its own juiced-copyN.ini (made from juiced.ini, with its own WorldPort) and log, and no
//    launcher pipe (the launcher talks to the first copy).
// GameSpy's UDP sockets take the next free port when theirs is in use (from 6500, 0x008F1230;
// 0x008E1D50 tries 100), but the game's own (0x00C1BBA0, co-op's traffic) is always 4200, with
// SO_REUSEADDR: every copy would get it and packets would go to any of them. So copy N binds
// 4200 + N - 1 (WSOCK32 bind, import slot 0x00DB8360). The game also tells others its address with
// 4200 written in (0x00811AC4 … 0x00811CBB, "mov word [reg+4], 0x1068" in the functions that make
// our address, 0x00811A70-0x00811CA0); the host learns the real port from packets, but two joined
// players reach each other by those (tried 2026-11-03: the second sent the third's packets to the
// host), so a copy writes its own port there. And when two players share an internet address,
// GameSpy's NAT step (0x008CDA00) uses the other's private address with port 4200 written in
// (0x008CDA38-0x008CDA41; right for another PC behind the same router, where the announced port is
// the router's): for an address of this PC it keeps the announced port, another copy's.
//
// All copies, so they can reach each other: the co-op host tells everyone the others' addresses
// as the internet sees them (new_conn), and a PC reaching itself through its router's public address
// only works on routers that loop it back. So each game lists the UDP ports it uses in shared memory,
// and a packet to a public address on a port another copy uses goes to 127.0.0.1 instead; what
// comes back from 127.0.0.1 is shown as from that public address, as the game expects. The game's
// sendto and recvfrom are WSOCK32's (import slots 0x00DB8390 and 0x00DB8388). With one copy
// running, nothing changes.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "SecondCopy.h"
#include "../FileLogger.h"
#include "../SafeWrite.h"
#include <safetyhook.hpp>

namespace SecondCopy
{
	namespace
	{
		constexpr UInt32 MutexCheck = 0x00BFA6B6;     // jne past "already running, quit"
		constexpr UInt32 SavePathCopied = 0x00520FD5; // just after the save folder is copied to 0x0144E650
		constexpr UInt32 SendToSlot = 0x00DB8390;
		constexpr UInt32 RecvFromSlot = 0x00DB8388;
		constexpr UInt32 BindSlot = 0x00DB8360;
		constexpr u_short GamePort = 4200;
		// The port's immediate in each "mov word ptr [reg+4], 0x1068" that writes our address.
		constexpr UInt32 OwnPortWrites[] = { 0x00811AC4, 0x00811B15, 0x00811BA8, 0x00811C11, 0x00811C7E, 0x00811CBB };
		constexpr int MaxCopies = 4;
		constexpr int Ports = 16;
		constexpr const char* Folders[MaxCopies] = { "", "Second copy", "Third copy", "Fourth copy" };

		// One entry per copy (0 = the first).
		struct Copy
		{
			volatile DWORD pid;
			volatile u_short ports[Ports];
		};
		struct Shared
		{
			volatile u_long publicAddress;   // network order; learned from the first packet sent to another copy
			Copy copies[MaxCopies];
		};

		int g_copy = -1;
		Shared* g_shared = nullptr;
		volatile bool g_running[MaxCopies] = {};   // which other copies are running
		volatile bool g_other = false;             // any of them
		SafetyHookMid g_savePath;
		char g_ini[32], g_log[32];

		using SendTo = int(WINAPI*)(SOCKET, const char*, int, int, const sockaddr*, int);
		using RecvFrom = int(WINAPI*)(SOCKET, char*, int, int, sockaddr*, int*);
		using Bind = int(WINAPI*)(SOCKET, const sockaddr*, int);
		SendTo g_sendTo = nullptr;
		RecvFrom g_recvFrom = nullptr;
		Bind g_bind = nullptr;

		// Sockets already looked at, so getsockname runs once per socket.
		SOCKET g_seen[Ports] = {};

		bool IsPrivate(u_long address)
		{
			const u_long a = ntohl(address);
			return (a >> 24) == 10 || (a >> 24) == 127 || (a >> 20) == 0xAC1 || (a >> 16) == 0xC0A8 || (a >> 16) == 0xA9FE || a == 0;
		}

		void Track(SOCKET s)
		{
			for (SOCKET seen : g_seen)
				if (seen == s) return;
			sockaddr_in local{};
			int size = sizeof(local);
			if (getsockname(s, reinterpret_cast<sockaddr*>(&local), &size) != 0 || local.sin_port == 0)
				return;
			for (SOCKET& seen : g_seen)
				if (!seen) { seen = s; break; }
			Copy& mine = g_shared->copies[g_copy];
			const u_short port = ntohs(local.sin_port);
			for (int i = 0; i < Ports; i++) {
				if (mine.ports[i] == port) return;
				if (!mine.ports[i]) { mine.ports[i] = port; return; }
			}
		}

		// Another running copy has this port open.
		bool OtherUses(u_short port)
		{
			for (int c = 0; c < MaxCopies; c++) {
				if (c == g_copy || !g_running[c]) continue;
				const Copy& other = g_shared->copies[c];
				for (int i = 0; i < Ports && other.ports[i]; i++)
					if (other.ports[i] == port) return true;
			}
			return false;
		}

		// The first packet to and from each address and port, in the log (while other copies run, to
		// see whether the copies reach each other).
		struct Route { u_long address; u_short port; bool sent; };
		Route g_routes[48];
		volatile LONG g_routeCount = 0;

		void LogRoute(const sockaddr* at, bool sent, bool redirected)
		{
			if (!g_other || !at || at->sa_family != AF_INET)
				return;
			const auto* address = reinterpret_cast<const sockaddr_in*>(at);
			const LONG count = g_routeCount;
			for (LONG i = 0; i < count && i < 48; i++)
				if (g_routes[i].address == address->sin_addr.s_addr && g_routes[i].port == address->sin_port && g_routes[i].sent == sent)
					return;
			const LONG at_ = InterlockedIncrement(&g_routeCount) - 1;
			if (at_ >= 48)
				return;
			g_routes[at_] = { address->sin_addr.s_addr, address->sin_port, sent };
			const u_long a = ntohl(address->sin_addr.s_addr);
			Logger::TypedLog(CHN_NET, "SecondCopy: first packet {} {}.{}.{}.{}:{}{}.\n", sent ? "to" : "from",
				a >> 24, (a >> 16) & 0xFF, (a >> 8) & 0xFF, a & 0xFF, ntohs(address->sin_port),
				redirected ? (sent ? " (sent to 127.0.0.1)" : " (came from 127.0.0.1)") : "");
		}

		int WINAPI HookedSendTo(SOCKET s, const char* buffer, int length, int flags, const sockaddr* to, int toLength)
		{
			Track(s);
			if (g_other && to && toLength >= static_cast<int>(sizeof(sockaddr_in)) && to->sa_family == AF_INET) {
				const auto* address = reinterpret_cast<const sockaddr_in*>(to);
				if (!IsPrivate(address->sin_addr.s_addr) && OtherUses(ntohs(address->sin_port))) {
					g_shared->publicAddress = address->sin_addr.s_addr;
					sockaddr_in local = *address;
					local.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
					LogRoute(to, true, true);
					return g_sendTo(s, buffer, length, flags, reinterpret_cast<const sockaddr*>(&local), sizeof(local));
				}
			}
			if (to && toLength >= static_cast<int>(sizeof(sockaddr_in)))
				LogRoute(to, true, false);
			return g_sendTo(s, buffer, length, flags, to, toLength);
		}

		int WINAPI HookedRecvFrom(SOCKET s, char* buffer, int length, int flags, sockaddr* from, int* fromLength)
		{
			Track(s);
			const int got = g_recvFrom(s, buffer, length, flags, from, fromLength);
			if (got >= 0 && g_other && from && fromLength && *fromLength >= static_cast<int>(sizeof(sockaddr_in)) && from->sa_family == AF_INET) {
				auto* address = reinterpret_cast<sockaddr_in*>(from);
				const u_long publicAddress = g_shared->publicAddress;
				const bool redirected = address->sin_addr.s_addr == htonl(INADDR_LOOPBACK) && publicAddress && OtherUses(ntohs(address->sin_port));
				if (redirected)
					address->sin_addr.s_addr = publicAddress;
				LogRoute(from, false, redirected);
			}
			return got;
		}

		int WINAPI HookedBind(SOCKET s, const sockaddr* name, int length)
		{
			if (g_copy > 0 && name && length >= static_cast<int>(sizeof(sockaddr_in)) && name->sa_family == AF_INET &&
				ntohs(reinterpret_cast<const sockaddr_in*>(name)->sin_port) == GamePort) {
				sockaddr_in own = *reinterpret_cast<const sockaddr_in*>(name);
				own.sin_port = htons(static_cast<u_short>(GamePort + g_copy));
				const int result = g_bind(s, reinterpret_cast<const sockaddr*>(&own), sizeof(own));
				Logger::TypedLog(CHN_NET, "SecondCopy: the game's port is {} for this copy ({}).\n", GamePort + g_copy,
					result == 0 ? "bound" : "couldn't bind");
				return result;
			}
			return g_bind(s, name, length);
		}

		// One of this PC's own IPv4 addresses (host order, as the game keeps them).
		bool OnThisPC(u_long address)
		{
			if (address == INADDR_LOOPBACK)
				return true;
			ULONG size = 0;
			GetIpAddrTable(nullptr, &size, FALSE);
			if (!size)
				return false;
			auto* table = static_cast<MIB_IPADDRTABLE*>(malloc(size));
			bool found = false;
			if (table && GetIpAddrTable(table, &size, FALSE) == NO_ERROR)
				for (DWORD i = 0; i < table->dwNumEntries && !found; i++)
					found = ntohl(table->table[i].dwAddr) == address;
			free(table);
			return found;
		}

		// 0x008CDA33, the same-subnet branch (esi = the peer, ecx = their private address, the
		// announced port at +0x2C).
		void SameSubnet(SafetyHookContext& ctx)
		{
			const uint16_t announced = *reinterpret_cast<const uint16_t*>(ctx.esi + 0x2C);
			*reinterpret_cast<uint32_t*>(ctx.esi + 0x28) = static_cast<uint32_t>(ctx.ecx);
			const bool copy = g_other && announced >= GamePort && announced < GamePort + MaxCopies && OnThisPC(static_cast<u_long>(ctx.ecx));
			*reinterpret_cast<uint16_t*>(ctx.esi + 0x2C) = copy ? announced : GamePort;
			if (copy)
				Logger::TypedLog(CHN_NET, "SecondCopy: a player on this PC is on port {}; using it.\n", announced);
			ctx.eip = 0x008CDA49;   // past the game's own writes and its log line
		}
		SafetyHookMid g_sameSubnet;

		bool Alive(DWORD pid)
		{
			if (!pid) return false;
			HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
			if (!process) return false;
			DWORD code = 0;
			const bool running = GetExitCodeProcess(process, &code) && code == STILL_ACTIVE;
			CloseHandle(process);
			return running;
		}

		// Which other copies are running, checked every few seconds (a closed copy leaves its entry).
		void Watch()
		{
			for (;;) {
				bool any = false;
				for (int c = 0; c < MaxCopies; c++) {
					if (c == g_copy) continue;
					const bool running = Alive(g_shared->copies[c].pid);
					if (running && !g_running[c])
						Logger::TypedLog(CHN_NET, "SecondCopy: copy {} is running; packets to it stay on this PC.\n", c + 1);
					else if (!running && g_running[c])
						Logger::TypedLog(CHN_NET, "SecondCopy: copy {} closed.\n", c + 1);
					g_running[c] = running;
					any = any || running;
				}
				g_other = any;
				Sleep(3000);
			}
		}

		void InitNetwork()
		{
			HANDLE mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, sizeof(Shared), L"Local\\StilwaterCopies4");
			if (!mapping) return;
			g_shared = static_cast<Shared*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Shared)));
			if (!g_shared) return;
			Copy& mine = g_shared->copies[g_copy];
			for (int i = 0; i < Ports; i++) mine.ports[i] = 0;
			mine.pid = GetCurrentProcessId();
			g_sendTo = *reinterpret_cast<SendTo*>(SendToSlot);
			g_recvFrom = *reinterpret_cast<RecvFrom*>(RecvFromSlot);
			SafeWrite32(SendToSlot, reinterpret_cast<UInt32>(&HookedSendTo));
			SafeWrite32(RecvFromSlot, reinterpret_cast<UInt32>(&HookedRecvFrom));
			g_bind = *reinterpret_cast<Bind*>(BindSlot);
			SafeWrite32(BindSlot, reinterpret_cast<UInt32>(&HookedBind));
			g_sameSubnet = safetyhook::create_mid(0x008CDA33, SameSubnet);
			CreateThread(nullptr, 0, [](LPVOID) -> DWORD { Watch(); return 0; }, nullptr, 0, nullptr);
		}
	}

	int Number()
	{
		if (g_copy < 0) {
			char value[8] = {};
			const int n = GetEnvironmentVariableA("STILWATER_COPY", value, sizeof(value)) ? atoi(value) : 1;
			g_copy = n >= 2 && n <= MaxCopies ? n - 1 : 0;
		}
		return g_copy + 1;
	}

	bool Active() { return Number() > 1; }

	const char* IniName()
	{
		if (!Active())
			return "juiced.ini";
		snprintf(g_ini, sizeof(g_ini), "juiced-copy%d.ini", Number());
		// First run: start from the first copy's settings, on a friend-character port of its own.
		if (CopyFileA("juiced.ini", g_ini, TRUE)) {
			char path[MAX_PATH], port[8];
			GetFullPathNameA(g_ini, MAX_PATH, path, nullptr);
			snprintf(port, sizeof(port), "%d", 29966 + Number() - 1);
			WritePrivateProfileStringA("Stilwater", "WorldPort", port, path);
		}
		return g_ini;
	}

	const char* LogName()
	{
		if (!Active())
			return "debug.txt";
		snprintf(g_log, sizeof(g_log), "debug-copy%d.txt", Number());
		return g_log;
	}

	void Init()
	{
		if (Active()) {
			SafeWrite8(MutexCheck, 0xEB);                      // jne -> jmp: start even with another copy running
			g_savePath = safetyhook::create_mid(SavePathCopied, [](SafetyHookContext&) {
				char* folder = reinterpret_cast<char*>(0x0144E650);
				strcat_s(folder, 0x100, "\\");
				strcat_s(folder, 0x100, Folders[g_copy]);
				CreateDirectoryA(folder, nullptr);
				Logger::TypedLog(CHN_DLL, "SecondCopy: saves and settings in {}.\n", folder);
			});
			int ports = 0;
			for (UInt32 at : OwnPortWrites) {
				const auto* code = reinterpret_cast<const uint8_t*>(at);
				if (code[-4] == 0x66 && code[-3] == 0xC7 && code[-1] == 0x04 && *reinterpret_cast<const uint16_t*>(at) == GamePort) {
					SafeWrite16(at, GamePort + g_copy);
					ports++;
				}
			}
			Logger::TypedLog(CHN_DLL, "SecondCopy: this is copy {} of the game ({} of 6 address ports now {}).\n", Number(), ports, GamePort + g_copy);
		}
		InitNetwork();
	}
}
