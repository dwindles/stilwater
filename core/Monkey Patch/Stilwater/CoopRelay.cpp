// CoopRelay.cpp (Stilwater)
// With three or more in co-op everyone connects to everyone (new_conn), so each pair of joined
// players has to reach each other through their routers. The host has each such pair try GameSpy's
// NAT negotiation (edges, 0x008CD4F0; started in 0x008CC3F0 with session message 47 "nat",
// 0x008CD660). When that fails and nothing has come from the other player yet (peer +0x48, set for
// every packet from a known peer in 0x00813BA0), the game stops sending to them (+0x1B8 = 0 in the
// NAT callback 0x008CC1F0; the per-peer send 0x00814670 skips such a peer) and the host kicks the
// newer of the two ("Kicking %ls due to failed NAT.", 0x00817470 at 0x008CD779 / 0x008CD79D). Two
// players never need it (only the host and one other), so a router that can't be punched through
// (some mobile hotspots, carrier NAT) cost a group its third player.
//
// Here such a pair's packets go through the host, whom everyone reaches because they joined through
// it. Each joined player says hello to each other joined player through the host. Once a player
// has heard back (so the other relays too; an older Stilwater drops what it doesn't know,
// 0x00813AD0), their packets go through the host from the start. So the game hears the other
// player before NAT negotiation ends and keeps them ("Failed to negotiated but I've received
// traffic."), and unanswered packets don't pile up (a peer has 128 packet buffers, 0x007F8810,
// before 0x007FA400 stops sending to them). A direct probe every second shows when the direct way
// works both ways; then they go direct, and when one side stops hearing the other, back through the
// host. NAT negotiation's own packets always go direct. A relayed packet is handed to the game as
// coming from the sender's address as this game knows it, so the game's matching (0x007FA070:
// address, port and the packet's first two bytes) and ordering are untouched. Players are named by
// their peer id (+0x1B0, the same on every machine), and the host only passes packets between
// players in its session.
//
// The game's own socket (*0x00E824C0, UDP 4200) is read on the network thread (0x00814320, under
// the mutex *0x02A157E4) and written from both threads. [Stilwater] CoopRelay: 1 on, 0 off, 2 always
// through the host (to try it with copies on one PC). Only with MaxCoopPlayers above 2.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "CoopRelay.h"
#include "CoopRelayLogic.h"
#include "CoopSize.h"
#include "../FileLogger.h"
#include "../GameConfig.h"
#include "../SafeWrite.h"
#include <safetyhook.hpp>

namespace CoopRelay
{
	namespace
	{
		constexpr UInt32 SendToSlot = 0x00DB8390;
		constexpr UInt32 RecvFromSlot = 0x00DB8388;
		constexpr UInt32 GameSocket = 0x00E824C0;
		constexpr UInt32 NetworkMutex = 0x02A157E4;
		constexpr int MaxPacket = 2048;
		constexpr int MaxPeers = 12;
		constexpr uint8_t NoId = 0xFF;

		// Our packets on the game's socket: this header, then (forwards) the game's packet. Byte 6 is
		// 0xFF: where the game's own check (0x00813AD0) reads a count of message blocks, so a game
		// without this never takes one for its own.
		constexpr char Magic[4] = { 'S', 'W', 'R', 'L' };
		enum : uint8_t { Forward = 1, Forwarded = 2, Probe = 3 };
#pragma pack(push, 1)
		struct Header
		{
			char magic[4];
			uint8_t kind;
			uint8_t hearsYou;   // a probe: whether its sender hears us directly
			uint8_t guard;      // 0xFF
			uint8_t peer;       // Forward: who it's for; Forwarded: who sent it; Probe: who sends it
		};
#pragma pack(pop)
		static_assert(sizeof(Header) == 8, "relay header");
		constexpr unsigned char NatNegMagic[6] = { 0xFD, 0xFC, 0x1E, 0x66, 0x6A, 0xB2 };

		struct Address
		{
			u_long ip = 0;      // network order, as in sockaddr_in
			u_short port = 0;
			bool operator==(const Address& other) const { return ip == other.ip && port == other.port; }
		};

		struct Peer
		{
			Address at;          // where this game sends to them (+0x28, +0x2C)
			uint8_t id = NoId;   // +0x1B0
			char name[32] = {};  // +0x4C, for the log
		};

		// Another joined player, by peer id (CoopRelayLogic.h decides).
		struct Link : Contact
		{
			uint8_t id = NoId;
		};

		using SendTo = int(WINAPI*)(SOCKET, const char*, int, int, const sockaddr*, int);
		using RecvFrom = int(WINAPI*)(SOCKET, char*, int, int, sockaddr*, int*);
		SendTo g_send = nullptr;
		RecvFrom g_recv = nullptr;
		int g_mode = 1;
		bool g_installed = false;
		CRITICAL_SECTION g_lock;

		// The session as of the last Update: on a client the host and the other joined players, on
		// the host every other player.
		bool g_coop = false, g_hosting = false;
		Peer g_host;
		uint8_t g_self = NoId;
		Peer g_peers[MaxPeers];
		int g_peerCount = 0;
		Link g_links[MaxPeers];
		int g_linkCount = 0;
		uint8_t g_passed[32][2];     // pairs the host has passed packets between (logged once)
		int g_passedCount = 0;
		SafetyHookMid g_keep[2];

		const Peer* ById(uint8_t id)
		{
			for (int i = 0; i < g_peerCount; i++)
				if (g_peers[i].id == id)
					return &g_peers[i];
			return nullptr;
		}

		const Peer* ByAddress(const Address& a)
		{
			for (int i = 0; i < g_peerCount; i++)
				if (g_peers[i].at == a)
					return &g_peers[i];
			return nullptr;
		}

		Link& LinkFor(uint8_t id)
		{
			for (int i = 0; i < g_linkCount; i++)
				if (g_links[i].id == id)
					return g_links[i];
			if (g_linkCount == MaxPeers) {         // full: reuse the oldest
				memmove(g_links, g_links + 1, sizeof(Link) * (MaxPeers - 1));
				g_linkCount--;
			}
			g_links[g_linkCount] = Link{};
			g_links[g_linkCount].id = id;
			return g_links[g_linkCount++];
		}

		void SendHeader(SOCKET s, const Address& to, uint8_t kind, uint8_t hearsYou, uint8_t peer)
		{
			const Header header{ { Magic[0], Magic[1], Magic[2], Magic[3] }, kind, hearsYou, 0xFF, peer };
			sockaddr_in target{};
			target.sin_family = AF_INET;
			target.sin_addr.s_addr = to.ip;
			target.sin_port = to.port;
			g_send(s, reinterpret_cast<const char*>(&header), sizeof(header), 0, reinterpret_cast<const sockaddr*>(&target), sizeof(target));
		}

		// They relay too (the lock is held).
		void NoteSpeaks(Link& link, const Peer& peer, DWORD now)
		{
			if (Speaks(link, now))
				Logger::TypedLog(CHN_NET, "CoopRelay: {} relays too; {}.\n", peer.name,
					link.relaying ? "through the host until the direct way works" : "they're reached directly");
		}

		int WINAPI Send(SOCKET s, const char* buffer, int length, int flags, const sockaddr* to, int toLength)
		{
			if (s != *reinterpret_cast<const SOCKET*>(GameSocket) || !buffer || !to || toLength < static_cast<int>(sizeof(sockaddr_in)) ||
				to->sa_family != AF_INET || length <= 0 || length > MaxPacket - static_cast<int>(sizeof(Header)) ||
				(length >= 6 && memcmp(buffer, NatNegMagic, sizeof(NatNegMagic)) == 0))   // NAT negotiation: always direct
				return g_send(s, buffer, length, flags, to, toLength);
			const auto* address = reinterpret_cast<const sockaddr_in*>(to);
			const Address dest{ address->sin_addr.s_addr, address->sin_port };
			EnterCriticalSection(&g_lock);
			const Peer* peer = g_coop && !g_hosting && g_host.at.ip && g_self != NoId ? ByAddress(dest) : nullptr;
			if (!peer) {
				LeaveCriticalSection(&g_lock);
				return g_send(s, buffer, length, flags, to, toLength);
			}
			Link& link = LinkFor(peer->id);
			const DWORD now = GetTickCount();
			if (!link.speaks) {
				if (now - link.lastHello >= HelloEvery) {   // an empty forward: hello
					link.lastHello = now;
					SendHeader(s, g_host.at, Forward, 0, peer->id);
				}
				LeaveCriticalSection(&g_lock);
				return g_send(s, buffer, length, flags, to, toLength);
			}
			const bool relay = ShouldRelay(link, now, g_mode == 2);
			if (relay != link.relaying) {
				link.relaying = relay;
				Logger::TypedLog(CHN_NET, "CoopRelay: {} {}{}.\n", relay ? "no direct way to" : "reaching", peer->name,
					relay ? "; through the host" : " directly");
			}
			if (now - link.lastProbe >= ProbeEvery) {   // either way, so each side knows whether the other hears it
				link.lastProbe = now;
				SendHeader(s, dest, Probe, HearsThem(link, now) ? 1 : 0, g_self);
			}
			if (!relay) {
				LeaveCriticalSection(&g_lock);
				return g_send(s, buffer, length, flags, to, toLength);
			}
			char packet[MaxPacket];
			const Header header{ { Magic[0], Magic[1], Magic[2], Magic[3] }, Forward, 0, 0xFF, peer->id };
			memcpy(packet, &header, sizeof(header));
			memcpy(packet + sizeof(Header), buffer, length);
			sockaddr_in host{};
			host.sin_family = AF_INET;
			host.sin_addr.s_addr = g_host.at.ip;
			host.sin_port = g_host.at.port;
			const int sent = g_send(s, packet, static_cast<int>(sizeof(Header)) + length, flags, reinterpret_cast<const sockaddr*>(&host), sizeof(host));
			LeaveCriticalSection(&g_lock);
			return sent < 0 ? sent : length;
		}

		// One of ours, read off the game's socket (the lock is held): passed on, handed to the game
		// (returns its length) or used up (returns -1).
		int Ours(SOCKET s, char* packet, int got, const Address& sender, char* buffer, int length, sockaddr* from, int* fromLength)
		{
			Header& header = *reinterpret_cast<Header*>(packet);
			const DWORD now = GetTickCount();
			if (!g_coop)
				return -1;
			if (g_hosting) {
				if (header.kind != Forward)
					return -1;
				const Peer* source = ByAddress(sender);
				const Peer* target = ById(header.peer);
				if (!source || !target || source == target)
					return -1;
				header.kind = Forwarded;
				header.peer = source->id;
				sockaddr_in to{};
				to.sin_family = AF_INET;
				to.sin_addr.s_addr = target->at.ip;
				to.sin_port = target->at.port;
				g_send(s, packet, got, 0, reinterpret_cast<const sockaddr*>(&to), sizeof(to));
				if (got > static_cast<int>(sizeof(Header))) {   // not a hello: log the pair once
					bool logged = false;
					for (int i = 0; i < g_passedCount && !logged; i++)
						logged = g_passed[i][0] == source->id && g_passed[i][1] == target->id;
					if (!logged && g_passedCount < 32) {
						g_passed[g_passedCount][0] = source->id;
						g_passed[g_passedCount++][1] = target->id;
						Logger::TypedLog(CHN_NET, "CoopRelay: passing {}'s packets on to {}.\n", source->name, target->name);
					}
				}
				return -1;
			}
			if (header.kind == Forwarded && sender == g_host.at) {
				const Peer* source = ById(header.peer);
				if (!source)
					return -1;
				Link& link = LinkFor(source->id);
				NoteSpeaks(link, *source, now);
				const int size = got - static_cast<int>(sizeof(Header));
				if (size <= 0) {   // a hello: answered, so they know we relay too even if nothing else of ours reaches them
					if (now - link.lastHello >= HelloEvery) {
						link.lastHello = now;
						SendHeader(s, g_host.at, Forward, 0, source->id);
					}
					return -1;
				}
				if (size > length)
					return -1;   // too big for the game
				memcpy(buffer, packet + sizeof(Header), size);
				if (from && fromLength && *fromLength >= static_cast<int>(sizeof(sockaddr_in))) {
					sockaddr_in as{};
					as.sin_family = AF_INET;
					as.sin_addr.s_addr = source->at.ip;
					as.sin_port = source->at.port;
					memcpy(from, &as, sizeof(as));
					*fromLength = sizeof(as);
				}
				return size;
			}
			if (header.kind == Probe) {
				const Peer* peer = ById(header.peer);
				if (!peer)
					return -1;
				Link& link = LinkFor(peer->id);
				if (sender == peer->at)   // from where the game expects them: the direct way works this way
					link.lastDirect = now;
				link.verdictAt = now;
				link.hearsUs = header.hearsYou != 0;
				NoteSpeaks(link, *peer, now);
			}
			return -1;
		}

		int WINAPI Receive(SOCKET s, char* buffer, int length, int flags, sockaddr* from, int* fromLength)
		{
			if (s != *reinterpret_cast<const SOCKET*>(GameSocket) || !buffer || length <= 0)
				return g_recv(s, buffer, length, flags, from, fromLength);
			char packet[MaxPacket];
			sockaddr_in source{};
			int sourceLength = sizeof(source);
			const int got = g_recv(s, packet, sizeof(packet), flags, reinterpret_cast<sockaddr*>(&source), &sourceLength);
			if (got < 0)
				return got;
			const Address sender{ source.sin_addr.s_addr, source.sin_port };
			const auto& header = *reinterpret_cast<const Header*>(packet);
			if (got >= static_cast<int>(sizeof(Header)) && memcmp(header.magic, Magic, sizeof(Magic)) == 0 && header.guard == 0xFF &&
				header.kind >= Forward && header.kind <= Probe) {
				EnterCriticalSection(&g_lock);
				const int handed = Ours(s, packet, got, sender, buffer, length, from, fromLength);
				LeaveCriticalSection(&g_lock);
				if (handed >= 0)
					return handed;
				WSASetLastError(WSAEWOULDBLOCK);
				return SOCKET_ERROR;
			}
			// One of the game's: a player whose packets come straight from where the game expects them.
			EnterCriticalSection(&g_lock);
			if (g_coop && !g_hosting)
				if (const Peer* peer = ByAddress(sender))
					LinkFor(peer->id).lastDirect = GetTickCount();
			LeaveCriticalSection(&g_lock);
			if (from && fromLength) {
				memcpy(from, &source, (std::min)(*fromLength, sourceLength));
				*fromLength = sourceLength;
			}
			if (got > length) {           // as the game's recvfrom would: what fits, and an error
				memcpy(buffer, packet, length);
				WSASetLastError(WSAEMSGSIZE);
				return SOCKET_ERROR;
			}
			memcpy(buffer, packet, got);
			return got;
		}

		Peer PeerAt(uintptr_t peer)   // address +0x28 and port +0x2C (host order), id +0x1B0, name +0x4C
		{
			Peer p;
			p.at = Address{ htonl(*reinterpret_cast<const uint32_t*>(peer + 0x28)), htons(*reinterpret_cast<const uint16_t*>(peer + 0x2C)) };
			p.id = *reinterpret_cast<const uint8_t*>(peer + 0x1B0);
			WideCharToMultiByte(CP_UTF8, 0, reinterpret_cast<const wchar_t*>(peer + 0x4C), 15, p.name, sizeof(p.name) - 1, nullptr, nullptr);
			if (!p.name[0])
				strcpy_s(p.name, "a player");
			return p;
		}

		// A failed NAT step between two joined players: keep the one the game would kick.
		void Keep(uintptr_t peer, UInt32 resume, SafetyHookContext& ctx)
		{
			if (*reinterpret_cast<const char*>(0x02528B49) == 0)
				return;   // multiplayer: as it was
			Logger::TypedLog(CHN_NET, "CoopRelay: {} couldn't connect to another player directly; kept.\n", PeerAt(peer).name);
			ctx.eip = resume;
		}
	}

	void Update()
	{
		if (!g_installed)
			return;
		static DWORD last = 0;
		const DWORD now = GetTickCount();
		if (now - last < 250)
			return;
		last = now;
		const HANDLE mutex = *reinterpret_cast<const HANDLE*>(NetworkMutex);
		if (!mutex || WaitForSingleObject(mutex, 0) != WAIT_OBJECT_0)
			return;   // the network thread has the session; next time
		bool coop = *reinterpret_cast<const char*>(0x02528B49) != 0, hosting = false;
		Peer host, peers[MaxPeers];
		uint8_t self = NoId;
		int count = 0;
		const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
		if (coop && session) {
			const bool client = *reinterpret_cast<const char*>(0x02528B56) != 0 && *reinterpret_cast<const char*>(0x02528B2B) == 0;
			hosting = !client && *reinterpret_cast<const char*>(session + 0x3F8) != 0;
			const uintptr_t hostPeer = *reinterpret_cast<const uintptr_t*>(session + 0x404);
			const uintptr_t selfPeer = *reinterpret_cast<const uintptr_t*>(session + 0x408);
			if (selfPeer)
				self = *reinterpret_cast<const uint8_t*>(selfPeer + 0x1B0);
			if (hostPeer && hostPeer != selfPeer)
				host = PeerAt(hostPeer);
			const uintptr_t first = *reinterpret_cast<const uintptr_t*>(session + 0x400);
			uintptr_t peer = first;
			for (int guard = 0; peer && guard < 16; ++guard) {
				// Other players' peers (byte 0 = 0) with an id; on a client not the host's.
				if (peer != selfPeer && peer != hostPeer && *reinterpret_cast<const char*>(peer) == 0 &&
					*reinterpret_cast<const uint8_t*>(peer + 0x1B0) != NoId && count < MaxPeers)
					peers[count++] = PeerAt(peer);
				peer = *reinterpret_cast<const uintptr_t*>(peer + 0x22CC);
				if (peer == first)
					break;
			}
		} else {
			coop = false;
		}
		ReleaseMutex(mutex);

		EnterCriticalSection(&g_lock);
		g_coop = coop;
		g_hosting = hosting;
		g_host = host;
		g_self = self;
		g_peerCount = count;
		for (int i = 0; i < count; i++)
			g_peers[i] = peers[i];
		int kept = 0;                       // links to players who are still here
		for (int i = 0; i < g_linkCount; i++)
			if (ById(g_links[i].id))
				g_links[kept++] = g_links[i];
		g_linkCount = kept;
		if (!coop)
			g_passedCount = 0;
		LeaveCriticalSection(&g_lock);
	}

	void Init()
	{
		g_mode = GameConfig::GetValue("Stilwater", "CoopRelay", 1,
			"Co-op past two players: when two joined players can't reach each other directly, their packets go through the host (0 = off, 2 = always, for trying it).");
		if (g_mode == 0 || CoopSize::Players() <= 2)
			return;
		InitializeCriticalSection(&g_lock);
		g_send = *reinterpret_cast<SendTo*>(SendToSlot);
		g_recv = *reinterpret_cast<RecvFrom*>(RecvFromSlot);
		SafeWrite32(SendToSlot, reinterpret_cast<UInt32>(&Send));
		SafeWrite32(RecvFromSlot, reinterpret_cast<UInt32>(&Receive));
		g_keep[0] = safetyhook::create_mid(0x008CD779, [](SafetyHookContext& ctx) { Keep(ctx.ecx, 0x008CD77E, ctx); });
		g_keep[1] = safetyhook::create_mid(0x008CD79D, [](SafetyHookContext& ctx) { Keep(ctx.ecx, 0x008CD7A2, ctx); });
		g_installed = true;
		Logger::TypedLog(CHN_NET, "CoopRelay: on{}; joined players who can't reach each other go through the host.\n",
			g_mode == 2 ? " (always, for trying it)" : "");
	}
}
