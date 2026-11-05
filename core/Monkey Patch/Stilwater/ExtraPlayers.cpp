// ExtraPlayers.cpp (Stilwater)
// Co-op past two players. The game's own co-op holds a host and one partner, so every other friend
// in a Stilwater world is a character in each player's game that copies where that friend is and
// which way they face: a spawned NPC (character [Stilwater] FriendCharacter) with its AI off that
// can't die, moved every frame.
//
// Network: every game listens on UDP [Stilwater] WorldPort (CoopPorts forwards it through the
// router like the game's own ports). A player who joins a world sends their state to the host's
// address about 20 times a second; the host sends its own state to everyone and passes each joined
// player's state on to the others. A state: id (random per run), name, whether the game is in its
// own co-op, position and facing. The host and its co-op partner already see each other, so two
// players who are both in the game's co-op get no character for each other.
//
// Characters are kept by the game's object handle (+0x44), looked up in its handle table
// (0x02149C64, 16 bytes per entry, the low 12 bits of the handle; 0x00960240 checks it the same
// way), so one the game removed (a load, a far-away cleanup) is noticed and spawned again instead
// of being written to. Friends further than 200 m away get no character.
//
// Name tags: every other player in the world (the co-op partner too, from their state) gets their
// name over their head, in their profile's colour and effect (glow, outline, pulse, rainbow) and
// with their crew tag, drawn with Overlay through the game's camera: its position (0x025F5B14),
// orientation rows right, up, forward (0x025F5B38, copied from the new camera at 0x004934F0) and
// field of view (0x025F5BA4, eased toward 0x025F5BA8), vertical, in degrees or radians.
//
// The game's own co-op players get the same tags: every second each sends its tag (its session
// name, crew, colour, effect) to every other player in the co-op session, on the world ports
// (29966-29969, the copies on one PC each have their own). A co-op character's session player is
// the peer whose id (+0x1B0) owns the character's network object (+0xB0, its first byte); the
// session's peers are at session (0x02528C14) +0x400, next +0x22CC, ours +0x408, name (wide) +0x4C,
// and the address their packets come from at +0x28 (host order).
#include "ExtraPlayers.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <random>
#include <thread>
#include <vector>

#include "Overlay.h"
#include "../FileLogger.h"
#include "../GameConfig.h"
#include "../General/General.h"

#pragma comment(lib, "ws2_32.lib")

namespace General
{
	extern bool IsSpawning;   // General.cpp: its spawn hook (0x0098EE0B) keeps the new NPC in CurrentNPC
	extern int CurrentNPC;
}

namespace ExtraPlayers
{
	namespace
	{
		constexpr char Magic[4] = { 'S', 'W', 'X', '2' };
		constexpr uint8_t StateKind = 1, ByeKind = 2, TagKind = 3;
		constexpr DWORD SendMs = 50, TimeoutMs = 5000, GhostDelayMs = 3000, RenderDelayMs = 100;
		constexpr float ShowWithin = 200.0f;

#pragma pack(push, 1)
		struct Packet
		{
			char magic[4];
			uint8_t kind, native, pad[2];
			uint32_t id, seq;
			char name[24];
			float pos[3], fwd[3];
			uint32_t colour;        // name tag: 0xRRGGBB
			uint8_t effect;         // Effect
			char crew[5];
		};

		enum Effect : uint8_t { Plain, Glow, Outline, Pulse, Rainbow };
		constexpr float TagsWithin = 80.0f, TagHeight = 2.0f;
#pragma pack(pop)

		struct Sample { DWORD at; float pos[3], fwd[3]; };

		struct Peer
		{
			sockaddr_in address{};
			std::string name, crew;
			uint32_t colour = 0xFFFFFF;
			uint8_t effect = Plain;
			bool native = false;
			Sample previous{}, latest{};
			DWORD seen = 0;
			uint32_t seq = 0;
		};

		// Shared with the network thread.
		std::mutex g_lock;
		std::map<uint32_t, Peer> g_peers;
		bool g_joined = false;              // we sent our state to a host (else we host whoever comes)
		sockaddr_in g_host{};
		std::string g_hostName, g_name = "Player", g_crew;
		uint32_t g_colour = 0xFFFFFF;
		uint8_t g_effect = Plain;

		// Name tags to draw: filled each frame by Update, drawn by DrawTags (both on the game's thread).
		struct Tag { float pos[3]; std::string name, crew; uint32_t colour; uint8_t effect; };
		std::vector<Tag> g_tags;

		// The game's own co-op: each player's tag style by session name (from their TagKind packets),
		// and where to send ours (filled by Update, sent by the network thread).
		struct CoopStyle { std::string crew; uint32_t colour = 0xFFFFFF; uint8_t effect = 0; DWORD seen = 0; };
		std::map<std::string, CoopStyle> g_coopStyles;
		std::vector<sockaddr_in> g_coopTargets;
		Packet g_coopMine{};
		constexpr float CoopTagHeight = 2.45f;   // above the game's own name and health bar
		Packet g_mine{};
		bool g_haveMine = false;

		SOCKET g_socket = INVALID_SOCKET;
		uint32_t g_id = 0;
		int g_port = 29966;
		std::string g_character = "npc_saint_male_lt";
		std::atomic<bool> g_ghost{ false };
		std::atomic<bool> g_ownTag{ false };   // our own name tag over our head, to see how it looks
		std::deque<Sample> g_history;       // the game thread's own, for the ghost

		// The game thread's own: each friend's character, by the game's object handle.
		std::map<uint32_t, uint32_t> g_characters;
		DWORD g_lastSpawn = 0;

		uintptr_t Player() { return *reinterpret_cast<uintptr_t*>(0x021703D4); }

		uintptr_t FromHandle(uint32_t handle)
		{
			if (!handle) return 0;
			const uintptr_t object = *reinterpret_cast<uintptr_t*>(0x02149C64 + (handle & 0xFFF) * 16);
			return object && *reinterpret_cast<uint32_t*>(object + 0x44) == handle ? object : 0;
		}

		void Teleport(uintptr_t human, const float* position)
		{
			uintptr_t saved;
			__asm {
				mov saved, esp
				push 0
				push -1
				push position
				mov eax, human
				mov ecx, 0x0095F090
				call ecx
				mov esp, saved
			}
		}

		uintptr_t Spawn()
		{
			int* character = General::GetCharacterID(g_character.c_str());
			if (!character) return 0;
			General::CurrentNPC = 0;
			General::IsSpawning = true;
			uintptr_t saved;
			__asm {
				mov saved, esp
				push character
				mov eax, ds:0x021703D4
				mov ecx, 0x0098E400
				call ecx
				mov esp, saved
			}
			General::IsSpawning = false;
			const uintptr_t human = static_cast<uintptr_t>(General::CurrentNPC);
			if (!human) return 0;
			*reinterpret_cast<uint8_t*>(human + 0x103) |= 8;                           // AI off (set_ignore_ai_flag)
			reinterpret_cast<void(__stdcall*)(uintptr_t, int)>(0x00966720)(human, 1);  // can't die
			return human;
		}

		void Remove(uint32_t handle)
		{
			if (const uintptr_t human = FromHandle(handle))
				General::DeleteNPC(static_cast<int>(human), 0);
		}

		void Place(uintptr_t human, const float* pos, const float* fwd)
		{
			Teleport(human, pos);
			// Orientation rows at +0x20: right, up, forward (SR2 is left-handed: right = up x forward).
			float flat[3] = { fwd[0], 0.0f, fwd[2] };
			const float length = std::sqrt(flat[0] * flat[0] + flat[2] * flat[2]);
			if (length < 1e-4f) return;
			flat[0] /= length;
			flat[2] /= length;
			float* m = reinterpret_cast<float*>(human + 0x20);
			m[0] = flat[2]; m[1] = 0; m[2] = -flat[0];
			m[3] = 0; m[4] = 1; m[5] = 0;
			m[6] = flat[0]; m[7] = 0; m[8] = flat[2];
		}

		void SendTo(const Packet& packet, const sockaddr_in& to)
		{
			sendto(g_socket, reinterpret_cast<const char*>(&packet), sizeof(packet), 0,
				reinterpret_cast<const sockaddr*>(&to), sizeof(to));
		}

		bool Same(const sockaddr_in& a, const sockaddr_in& b)
		{
			return a.sin_addr.s_addr == b.sin_addr.s_addr && a.sin_port == b.sin_port;
		}

		void NetThread()
		{
			DWORD lastSend = 0;
			uint32_t seq = 0;
			for (;;) {
				fd_set read;
				FD_ZERO(&read);
				FD_SET(g_socket, &read);
				timeval wait{ 0, 20000 };
				if (select(0, &read, nullptr, nullptr, &wait) > 0) {
					Packet packet;
					sockaddr_in from{};
					int length = sizeof(from);
					const int got = recvfrom(g_socket, reinterpret_cast<char*>(&packet), sizeof(packet), 0,
						reinterpret_cast<sockaddr*>(&from), &length);
					if (got == sizeof(packet) && memcmp(packet.magic, Magic, 4) == 0 && packet.id != g_id) {
						std::lock_guard lock(g_lock);
						const DWORD now = GetTickCount();
						if (packet.kind == TagKind) {
							CoopStyle& style = g_coopStyles[std::string(packet.name, strnlen(packet.name, sizeof(packet.name)))];
							style.crew.assign(packet.crew, strnlen(packet.crew, sizeof(packet.crew)));
							style.colour = packet.colour & 0xFFFFFF;
							style.effect = packet.effect <= Rainbow ? packet.effect : Plain;
							style.seen = now;
							continue;   // not a world player, and not passed on
						}
						if (packet.kind == ByeKind)
							g_peers.erase(packet.id);
						else if (packet.kind == StateKind) {
							Peer& peer = g_peers[packet.id];
							if (!peer.seen || packet.seq > peer.seq || packet.seq + 1000 < peer.seq) {
								if (!peer.seen)
									Logger::TypedLog(CHN_NET, "ExtraPlayers: {} is in the world.\n", std::string(packet.name, strnlen(packet.name, 24)));
								peer.address = from;
								peer.name.assign(packet.name, strnlen(packet.name, sizeof(packet.name)));
								peer.crew.assign(packet.crew, strnlen(packet.crew, sizeof(packet.crew)));
								peer.colour = packet.colour & 0xFFFFFF;
								peer.effect = packet.effect <= Rainbow ? packet.effect : Plain;
								peer.native = packet.native != 0;
								peer.previous = peer.seen ? peer.latest : Sample{ now, {}, {} };
								peer.latest.at = now;
								memcpy(peer.latest.pos, packet.pos, sizeof(packet.pos));
								memcpy(peer.latest.fwd, packet.fwd, sizeof(packet.fwd));
								if (!peer.previous.at) peer.previous = peer.latest;
								peer.seen = now;
								peer.seq = packet.seq;
							}
						}
						// The host passes each player's packets on to everyone else.
						if (!g_joined)
							for (auto& [id, other] : g_peers)
								if (id != packet.id && !Same(other.address, from))
									SendTo(packet, other.address);
					}
				}
				const DWORD now = GetTickCount();
				static DWORD lastTag = 0;
				if (now - lastTag >= 1000) {
					lastTag = now;
					std::lock_guard lock(g_lock);
					for (const sockaddr_in& to : g_coopTargets)
						SendTo(g_coopMine, to);
				}
				if (now - lastSend >= SendMs) {
					lastSend = now;
					std::lock_guard lock(g_lock);
					for (auto it = g_peers.begin(); it != g_peers.end();)
						it = now - it->second.seen > TimeoutMs ? g_peers.erase(it) : std::next(it);
					if (g_haveMine) {
						g_mine.seq = ++seq;
						if (g_joined)
							SendTo(g_mine, g_host);
						else
							for (auto& [id, peer] : g_peers)
								SendTo(g_mine, peer.address);
					}
				}
			}
		}

		std::string PeerName(uintptr_t peer)
		{
			const auto* wide = reinterpret_cast<const wchar_t*>(peer + 0x4C);
			char text[64] = {};
			WideCharToMultiByte(CP_UTF8, 0, wide, static_cast<int>(wcsnlen(wide, 31)), text, sizeof(text) - 1, nullptr, nullptr);
			return text;
		}

		// The game's own co-op players: our tag to send, where to, and a tag over each of them.
		void CoopTags(uintptr_t me, const float* mine)
		{
			const uintptr_t session = *reinterpret_cast<const uintptr_t*>(0x02528C14);
			std::vector<sockaddr_in> targets;
			if (!session || *reinterpret_cast<const char*>(0x02528B49) == 0) {
				std::lock_guard lock(g_lock);
				g_coopTargets.clear();
				return;
			}
			const uintptr_t self = *reinterpret_cast<const uintptr_t*>(session + 0x408);
			const uintptr_t first = *reinterpret_cast<const uintptr_t*>(session + 0x400);
			std::map<uint8_t, std::string> names;   // peer id -> session name
			uintptr_t peer = first;
			for (int guard = 0; peer && guard < 16; ++guard) {
				names[*reinterpret_cast<const uint8_t*>(peer + 0x1B0)] = PeerName(peer);
				if (peer != self) {
					const uint32_t address = *reinterpret_cast<const uint32_t*>(peer + 0x28);
					for (int port = 29966; port < 29970; port++) {
						sockaddr_in to{};
						to.sin_family = AF_INET;
						to.sin_addr.s_addr = htonl(address);
						to.sin_port = htons(static_cast<u_short>(port));
						if (address) targets.push_back(to);
					}
				}
				peer = *reinterpret_cast<const uintptr_t*>(peer + 0x22CC);
				if (peer == first) break;
			}
			std::map<std::string, CoopStyle> styles;
			{
				std::lock_guard lock(g_lock);
				g_coopTargets = targets;
				memcpy(g_coopMine.magic, Magic, 4);
				g_coopMine.kind = TagKind;
				g_coopMine.id = g_id;
				strncpy_s(g_coopMine.name, self ? PeerName(self).c_str() : g_name.c_str(), _TRUNCATE);
				strncpy_s(g_coopMine.crew, g_crew.c_str(), _TRUNCATE);
				g_coopMine.colour = g_colour;
				g_coopMine.effect = g_effect;
				styles = g_coopStyles;
			}

			const uintptr_t head = *reinterpret_cast<const uintptr_t*>(0x0217043C);
			uintptr_t player = head;
			for (int guard = 0; player && guard < 16; ++guard) {
				const bool us = player == me;
				const char* object = *reinterpret_cast<const char* const*>(player + 0xB0);
				const auto name = object ? names.find(static_cast<uint8_t>(*object)) : names.end();
				if (!us && name != names.end() && !name->second.empty()) {   // our own: "Show my name tag", above
					const float* at = reinterpret_cast<const float*>(player + 0x14);
					const float dx = at[0] - mine[0], dy = at[1] - mine[1], dz = at[2] - mine[2];
					const bool shown = std::any_of(g_tags.begin(), g_tags.end(), [&](const Tag& t) { return t.name == name->second; });
					if (!shown && dx * dx + dy * dy + dz * dz < TagsWithin * TagsWithin) {
						Tag tag{ { at[0], at[1] + CoopTagHeight - TagHeight, at[2] }, name->second, "", 0xFFFFFF, Plain };
						if (const auto style = styles.find(name->second); style != styles.end()) {
							tag.crew = style->second.crew; tag.colour = style->second.colour; tag.effect = style->second.effect;
						}
						g_tags.push_back(tag);
					}
				}
				player = *reinterpret_cast<const uintptr_t*>(player + 0x1294);
				if (player == head) break;
			}
		}

		void Lerp(const Sample& a, const Sample& b, DWORD at, float* pos)
		{
			const float span = static_cast<float>(b.at - a.at);
			float t = span > 0 ? static_cast<float>(static_cast<int>(at - a.at)) / span : 1.0f;
			t = t < 0 ? 0 : t > 1.5f ? 1.5f : t;   // a little past the last sample keeps it moving
			for (int k = 0; k < 3; k++)
				pos[k] = a.pos[k] + (b.pos[k] - a.pos[k]) * t;
		}
	}

	void Init()
	{
		g_port = GameConfig::GetValue("Stilwater", "WorldPort", 29966,
			"UDP port for co-op past two players: friends who join your world connect to it.");
		char character[64] = {};
		GameConfig::GetStringValue("Stilwater", "FriendCharacter", "npc_saint_male_lt", character,
			"Character the game shows for friends past your co-op partner (a character.xtbl name).");
		if (character[0]) g_character = character;
		g_id = std::random_device{}() | 1;

		WSADATA wsa;
		WSAStartup(MAKEWORD(2, 2), &wsa);
		g_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
		sockaddr_in local{};
		local.sin_family = AF_INET;
		local.sin_port = htons(static_cast<u_short>(g_port));
		if (bind(g_socket, reinterpret_cast<sockaddr*>(&local), sizeof(local)) != 0) {
			Logger::TypedLog(CHN_NET, "ExtraPlayers: UDP port {} is taken; friends can join others' worlds but not yours.\n", g_port);
			local.sin_port = 0;
			bind(g_socket, reinterpret_cast<sockaddr*>(&local), sizeof(local));
		}
		else
			Logger::TypedLog(CHN_NET, "ExtraPlayers: world open on UDP port {}.\n", g_port);
		std::thread(NetThread).detach();
	}

	void Join(const std::string& address, const std::string& host)
	{
		addrinfo hints{}, * found = nullptr;
		hints.ai_family = AF_INET;
		hints.ai_socktype = SOCK_DGRAM;
		if (getaddrinfo(address.c_str(), std::to_string(g_port).c_str(), &hints, &found) != 0 || !found) {
			Logger::TypedLog(CHN_NET, "ExtraPlayers: can't reach {}.\n", address);
			return;
		}
		std::lock_guard lock(g_lock);
		g_host = *reinterpret_cast<sockaddr_in*>(found->ai_addr);
		freeaddrinfo(found);
		g_joined = true;
		g_hostName = host;
		g_peers.clear();
		Logger::TypedLog(CHN_NET, "ExtraPlayers: joined {}'s world.\n", host);
	}

	void Leave()
	{
		std::lock_guard lock(g_lock);
		Packet bye{};
		memcpy(bye.magic, Magic, 4);
		bye.kind = ByeKind;
		bye.id = g_id;
		if (g_joined)
			SendTo(bye, g_host);
		else
			for (auto& [id, peer] : g_peers)
				SendTo(bye, peer.address);
		g_joined = false;
		g_peers.clear();
	}

	void SetName(const std::string& name)
	{
		std::lock_guard lock(g_lock);
		if (!name.empty()) g_name = name;
	}

	void SetStyle(const std::string& style)
	{
		uint32_t colour = 0xFFFFFF;
		uint8_t effect = Plain;
		std::string crew;
		size_t at = 0;
		while (at < style.size()) {
			const size_t end = std::min(style.find(';', at), style.size());
			const std::string part = style.substr(at, end - at);
			const size_t eq = part.find('=');
			if (eq != std::string::npos) {
				const std::string key = part.substr(0, eq), value = part.substr(eq + 1);
				if (key == "color" && value.size() == 6) colour = strtoul(value.c_str(), nullptr, 16) & 0xFFFFFF;
				else if (key == "effect")
					effect = value == "glow" ? Glow : value == "outline" ? Outline : value == "pulse" ? Pulse : value == "rainbow" ? Rainbow : Plain;
				else if (key == "crew") crew = value.substr(0, 4);
			}
			at = end + 1;
		}
		std::lock_guard lock(g_lock);
		g_colour = colour;
		g_effect = effect;
		g_crew = crew;
	}

	bool HasTags() { return !g_tags.empty(); }

	void DrawTags()
	{
		const float* camera = reinterpret_cast<const float*>(0x025F5B14);
		const float* rows = reinterpret_cast<const float*>(0x025F5B38);          // right, up, forward
		float fov = *reinterpret_cast<const float*>(0x025F5BA4);
		if (fov > 3.5f) fov *= 3.14159265f / 180.0f;                               // degrees
		if (!(fov > 0.2f && fov < 3.0f)) fov = 1.0f;
		const float width = static_cast<float>(Overlay::Width()), height = static_cast<float>(Overlay::Height());
		const float focal = height * 0.5f / std::tan(fov * 0.5f);
		const float s = Overlay::Scale();
		const float t = GetTickCount() / 1000.0f;
		for (const Tag& tag : g_tags) {
			const float rel[3] = { tag.pos[0] - camera[0], tag.pos[1] + TagHeight - camera[1], tag.pos[2] - camera[2] };
			const float x = rel[0] * rows[0] + rel[1] * rows[1] + rel[2] * rows[2];
			const float y = rel[0] * rows[3] + rel[1] * rows[4] + rel[2] * rows[5];
			const float z = rel[0] * rows[6] + rel[1] * rows[7] + rel[2] * rows[8];
			if (z < 0.5f || z > TagsWithin) continue;
			const float cx = width * 0.5f + x / z * focal, cy = height * 0.5f - y / z * focal;
			if (cx < -200 || cx > width + 200 || cy < -50 || cy > height + 50) continue;
			// Fades out over the last fifth of the range.
			const float fade = std::min(1.0f, (TagsWithin - z) / (TagsWithin * 0.2f));
			const uint32_t a = static_cast<uint32_t>(255 * fade) << 24;
			const Overlay::Font font = Overlay::Font::Body;
			const float nameW = Overlay::TextWidth(tag.name, font);
			const float crewW = tag.crew.empty() ? 0 : Overlay::TextWidth(tag.crew, Overlay::Font::Small) + 10 * s;
			const float w = nameW + crewW + 16 * s, h = Overlay::LineHeight(font) + 6 * s;
			float x0 = cx - w / 2;
			const float y0 = cy - h;
			Overlay::RoundRect(x0, y0, w, h, 3 * s, (static_cast<uint32_t>(110 * fade) << 24));
			x0 += 8 * s;
			if (!tag.crew.empty()) {
				Overlay::RoundRect(x0, y0 + 5 * s, crewW - 4 * s, h - 10 * s, 2 * s, (static_cast<uint32_t>(70 * fade) << 24) | 0xFFFFFF);
				Overlay::Text(x0 + 3 * s, y0 + (h - Overlay::LineHeight(Overlay::Font::Small)) / 2, tag.crew, Overlay::Font::Small, a | 0xC8C8CC);
				x0 += crewW;
			}
			const float ty = y0 + 3 * s;
			uint32_t colour = tag.colour;
			if (tag.effect == Pulse) {
				const float k = 0.75f + 0.25f * std::sin(t * 3.5f);
				colour = (static_cast<uint32_t>(((colour >> 16) & 255) * k) << 16) | (static_cast<uint32_t>(((colour >> 8) & 255) * k) << 8)
					| static_cast<uint32_t>((colour & 255) * k);
			}
			if (tag.effect == Glow || tag.effect == Pulse) {
				const uint32_t halo = (static_cast<uint32_t>((tag.effect == Pulse ? 50 + 40 * std::sin(t * 3.5f) : 70) * fade) << 24) | (tag.colour & 0xFFFFFF);
				for (int dx = -2; dx <= 2; dx += 2)
					for (int dy = -2; dy <= 2; dy += 2)
						if (dx || dy) Overlay::Text(x0 + dx * s, ty + dy * s, tag.name, font, halo);
			}
			if (tag.effect == Outline || tag.effect == Plain)
				for (int dx = -1; dx <= 1; dx++)
					for (int dy = -1; dy <= 1; dy++)
						if (dx || dy) Overlay::Text(x0 + dx * s, ty + dy * s, tag.name, font, a & (tag.effect == Outline ? 0xFF000000 : 0x80000000));
			if (tag.effect == Rainbow) {
				// Letter by letter, the hue moving along the name.
				float lx = x0;
				for (size_t i = 0; i < tag.name.size();) {
					size_t n = 1;
					while (i + n < tag.name.size() && (static_cast<unsigned char>(tag.name[i + n]) & 0xC0) == 0x80) n++;
					const std::string ch = tag.name.substr(i, n);
					const float hue = std::fmod(t * 120.0f + lx * 1.5f / s, 360.0f) / 60.0f;
					const float f = hue - std::floor(hue);
					const int sector = static_cast<int>(hue) % 6;
					const float rgb[6][3] = { {1, f, 0}, {1 - f, 1, 0}, {0, 1, f}, {0, 1 - f, 1}, {f, 0, 1}, {1, 0, 1 - f} };
					const uint32_t c = (static_cast<uint32_t>(255 * rgb[sector][0]) << 16) | (static_cast<uint32_t>(255 * rgb[sector][1]) << 8)
						| static_cast<uint32_t>(255 * rgb[sector][2]);
					Overlay::Text(lx + s, ty + s, ch, font, a & 0x90000000);
					lx += Overlay::Text(lx, ty, ch, font, a | c);
					i += n;
				}
			}
			else
				Overlay::Text(x0, ty, tag.name, font, a | colour);
		}
	}

	bool Ghost() { return g_ghost; }
	void SetGhost(bool on) { g_ghost = on; }
	bool OwnTag() { return g_ownTag; }
	void SetOwnTag(bool on) { g_ownTag = on; }

	std::string Status()
	{
		std::lock_guard lock(g_lock);
		const size_t others = g_peers.size();
		if (g_joined)
			return "In " + g_hostName + "'s world, " + std::to_string(others) + (others == 1 ? " other player" : " other players");
		return others ? "Hosting " + std::to_string(others) + (others == 1 ? " friend" : " friends") : "Nobody in your world";
	}

	void Update()
	{
		const uintptr_t me = Player();
		const DWORD now = GetTickCount();
		const bool loaded = me && *General::GameLoaded == 1;
		Sample mine{ now, {}, {} };
		bool native = false;
		if (loaded) {
			memcpy(mine.pos, reinterpret_cast<float*>(me + 0x14), sizeof(mine.pos));
			memcpy(mine.fwd, reinterpret_cast<float*>(me + 0x38), sizeof(mine.fwd));
			native = General::isCoop();
		}
		std::map<uint32_t, Peer> peers;
		{
			std::lock_guard lock(g_lock);
			g_haveMine = loaded;
			if (loaded) {
				memcpy(g_mine.magic, Magic, 4);
				g_mine.kind = StateKind;
				g_mine.native = native;
				g_mine.id = g_id;
				strncpy_s(g_mine.name, g_name.c_str(), _TRUNCATE);
				strncpy_s(g_mine.crew, g_crew.c_str(), _TRUNCATE);
				g_mine.colour = g_colour;
				g_mine.effect = g_effect;
				memcpy(g_mine.pos, mine.pos, sizeof(mine.pos));
				memcpy(g_mine.fwd, mine.fwd, sizeof(mine.fwd));
			}
			peers = g_peers;
		}

		// Testing alone: a friend that is you, 3 s late.
		if (loaded && g_ghost) {
			g_history.push_back(mine);
			while (g_history.size() > 2 && now - g_history[1].at > GhostDelayMs)
				g_history.pop_front();
			if (now - g_history.front().at >= GhostDelayMs) {
				Peer ghost;
				ghost.name = "Ghost";
				{
					std::lock_guard lock(g_lock);
					ghost.colour = g_colour;
					ghost.effect = g_effect;
					ghost.crew = g_crew;
				}
				ghost.previous = g_history.front();
				ghost.latest = g_history.size() > 1 ? g_history[1] : g_history.front();
				// Played back on its own clock: shift it so "now" falls between the two samples.
				ghost.previous.at += GhostDelayMs - RenderDelayMs;
				ghost.latest.at += GhostDelayMs - RenderDelayMs;
				ghost.seen = now;
				peers[g_id ^ 0xFFFFFFFF] = ghost;
			}
		}
		else
			g_history.clear();

		// Characters for players who left, or who aren't shown any more.
		for (auto it = g_characters.begin(); it != g_characters.end();) {
			const auto peer = peers.find(it->first);
			bool keep = loaded && peer != peers.end() && !(native && peer->second.native);
			if (keep) {
				const float* p = peer->second.latest.pos;
				const float dx = p[0] - mine.pos[0], dy = p[1] - mine.pos[1], dz = p[2] - mine.pos[2];
				keep = dx * dx + dy * dy + dz * dz < ShowWithin * ShowWithin;
			}
			if (!keep) {
				if (loaded) Remove(it->second);
				it = g_characters.erase(it);
			}
			else
				++it;
		}
		if (!loaded) { g_tags.clear(); return; }

		g_tags.clear();
		if (g_ownTag) {
			std::lock_guard lock(g_lock);
			g_tags.push_back({ { mine.pos[0], mine.pos[1], mine.pos[2] }, g_name, g_crew, g_colour, g_effect });
		}
		for (auto& [id, peer] : peers) {
			float at[3];
			Lerp(peer.previous, peer.latest, now - RenderDelayMs, at);
			const float tx = at[0] - mine.pos[0], ty = at[1] - mine.pos[1], tz = at[2] - mine.pos[2];
			if (tx * tx + ty * ty + tz * tz < TagsWithin * TagsWithin)
				g_tags.push_back({ { at[0], at[1], at[2] }, peer.name, peer.crew, peer.colour, peer.effect });
		}
		CoopTags(me, mine.pos);
		for (auto& [id, peer] : peers) {
			if (native && peer.native) continue;
			const float* p = peer.latest.pos;
			const float dx = p[0] - mine.pos[0], dy = p[1] - mine.pos[1], dz = p[2] - mine.pos[2];
			if (dx * dx + dy * dy + dz * dz >= ShowWithin * ShowWithin) continue;
			uintptr_t human = FromHandle(g_characters[id]);
			if (!human) {
				if (now - g_lastSpawn < 1000) continue;   // one new character a second at most
				g_lastSpawn = now;
				human = Spawn();
				if (!human) continue;
				g_characters[id] = *reinterpret_cast<uint32_t*>(human + 0x44);
				Logger::TypedLog(CHN_NET, "ExtraPlayers: a character for {}.\n", peer.name);
			}
			float pos[3];
			Lerp(peer.previous, peer.latest, now - RenderDelayMs, pos);
			Place(human, pos, peer.latest.fwd);
		}
	}
}
