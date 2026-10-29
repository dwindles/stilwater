// InviteMenu.cpp (Stilwater)
// The Insert menu: a Friends tab (invite a friend to your co-op game, or join the game a friend
// invited you to) and the Trainer tab (Trainer.cpp's cheats), drawn with Overlay, plus pop-up
// notifications (invites, friends coming online, what the launcher reports).
//
// The game's own invites don't work on PC (0x0081EFE0 queues them and never sends), so friends and
// invites go through the launcher, which stays signed in to Stilwater Online while the game runs: a
// named pipe, \\.\pipe\stilwater-launcher (launcher/GamePipe.cs has the message format). Joining
// asks the server to show the joiner only that friend's game in the co-op list (presence.py
// cmd_swjoin), so the game's own join finds it.
//
// While the menu is open the game keeps running but the player's controls are off, and the mouse
// moves the menu's own cursor (the panel is dragged by its title bar; where it is goes in juiced.ini).
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <safetyhook.hpp>

#include "InviteMenu.h"
#include "Overlay.h"
#include "Trainer.h"
#include "../FileLogger.h"
#include "../GameConfig.h"
#include "../General/General.h"
#include "../UtilsGlobal.h"

// MainHooks.cpp
bool IsKeyPressed(unsigned char Key, bool Hold);

namespace Gamespy
{
	uintptr_t get_pc_session();
	bool isSessionCoop(uintptr_t session);
}

namespace InviteMenu
{
	namespace
	{
		constexpr wchar_t PipeName[] = L"\\\\.\\pipe\\stilwater-launcher";
		constexpr char Field = '\x1f', Item = '\x1e';
		constexpr DWORD NoteMs = 6000, InviteMs = 5 * 60 * 1000;

		// Colours (ARGB), the launcher's.
		constexpr uint32_t Shade = 0x99000000, Panel = 0xF5111113, Line = 0xFF26262B, Selected = 0xFF26262D,
			Accent = 0xFFF2B632, Text = 0xFFECECEE, Muted = 0xFF9B9BA3, Faint = 0xFF6C6C74, Green = 0xFF4CC38A;

		struct Friend { int id = 0; int status = 0; std::string name, activity; };
		struct Invite { int id = 0; std::string name; DWORD at = 0; };
		struct Note { std::string title, text; DWORD at = 0; };
		struct Row { std::string label, value; uint32_t dot = 0; bool adjustable = false, dim = false; };

		unsigned char g_key = VK_INSERT, g_altKey = 0;
		bool g_open = false;
		int g_tab = 0, g_selected = 0;              // tab 0 friends, 1 trainer, 2 the game's cheats
		int g_first = 0;                            // the top row shown; the wheel moves it, not the selection

		// Shared with the pipe thread and the Present hook.
		std::mutex g_lock;
		bool g_connected = false, g_haveFriends = false;
		std::string g_me;
		std::vector<Friend> g_friends;
		std::vector<Invite> g_invites;
		std::deque<Note> g_notes;
		std::vector<Row> g_rows;                     // what the open tab shows, made on the game thread
		std::string g_empty;                         // shown when the tab has no rows

		HANDLE g_pipe = INVALID_HANDLE_VALUE;
		std::mutex g_writing;

		void AddNote(const std::string& title, const std::string& text)
		{
			std::lock_guard lock(g_lock);
			g_notes.push_back({ title, text, GetTickCount() });
			while (g_notes.size() > 4) g_notes.pop_front();
		}

		std::vector<std::string> Split(const std::string& text, char separator)
		{
			std::vector<std::string> parts;
			size_t start = 0;
			for (size_t at; (at = text.find(separator, start)) != std::string::npos; start = at + 1)
				parts.push_back(text.substr(start, at - start));
			parts.push_back(text.substr(start));
			return parts;
		}

		// --- the launcher

		bool Wait(HANDLE pipe, OVERLAPPED& overlapped, BOOL started, DWORD& bytes)
		{
			if (!started && GetLastError() != ERROR_IO_PENDING) return false;
			return GetOverlappedResult(pipe, &overlapped, &bytes, TRUE) != FALSE;
		}

		void Send(const std::string& line)
		{
			std::lock_guard lock(g_writing);
			if (g_pipe == INVALID_HANDLE_VALUE) return;
			const std::string data = line + "\n";
			OVERLAPPED overlapped{};
			overlapped.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
			DWORD written = 0;
			Wait(g_pipe, overlapped, WriteFile(g_pipe, data.data(), (DWORD)data.size(), nullptr, &overlapped), written);
			CloseHandle(overlapped.hEvent);
		}

		void Handle(const std::string& line)
		{
			const auto f = Split(line, Field);
			const std::string& kind = f[0];
			if (kind == "me" && f.size() > 1) {
				std::lock_guard lock(g_lock);
				g_me = f[1];
			}
			else if (kind == "friends") {
				std::vector<Friend> friends;
				for (size_t i = 1; i < f.size(); i++) {
					const auto p = Split(f[i], Item);
					if (p.size() >= 4)
						friends.push_back({ atoi(p[0].c_str()), atoi(p[1].c_str()), p[2], p[3] });
				}
				std::vector<std::string> cameOnline;
				{
					std::lock_guard lock(g_lock);
					if (g_haveFriends)
						for (const Friend& now : friends)
							for (const Friend& before : g_friends)
								if (now.id == before.id && before.status == 0 && now.status != 0)
									cameOnline.push_back(now.name);
					g_friends = std::move(friends);
					g_haveFriends = true;
				}
				for (const auto& name : cameOnline)
					AddNote(name + " is online", "");
			}
			else if (kind == "invite" && f.size() > 2) {
				{
					std::lock_guard lock(g_lock);
					const int id = atoi(f[1].c_str());
					g_invites.erase(std::remove_if(g_invites.begin(), g_invites.end(), [&](const Invite& i) { return i.id == id; }), g_invites.end());
					g_invites.insert(g_invites.begin(), { id, f[2], GetTickCount() });
				}
				AddNote(f[2] + " invited you to co-op", "Press Insert to join.");
			}
			else if (kind == "joining" && f.size() > 2) {
				{
					std::lock_guard lock(g_lock);
					const int id = atoi(f[1].c_str());
					g_invites.erase(std::remove_if(g_invites.begin(), g_invites.end(), [&](const Invite& i) { return i.id == id; }), g_invites.end());
				}
				AddNote("Joining " + f[2], "Pause > Co-op > join an online game. Theirs is the only one listed.");
			}
			else if (kind == "note" && f.size() > 1)
				AddNote(f[1], "");
		}

		void PipeThread()
		{
			for (;;) {
				HANDLE pipe = CreateFileW(PipeName, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
				if (pipe == INVALID_HANDLE_VALUE) {
					Sleep(3000);
					continue;
				}
				{
					std::lock_guard write(g_writing);
					g_pipe = pipe;
				}
				{
					std::lock_guard lock(g_lock);
					g_connected = true;
				}
				Logger::TypedLog(CHN_DLL, "InviteMenu: connected to the launcher.\n");
				Send("hello");
				std::string buffer;
				char chunk[4096];
				OVERLAPPED overlapped{};
				overlapped.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
				for (;;) {
					DWORD read = 0;
					ResetEvent(overlapped.hEvent);
					if (!Wait(pipe, overlapped, ReadFile(pipe, chunk, sizeof(chunk), nullptr, &overlapped), read) || read == 0)
						break;
					buffer.append(chunk, read);
					for (size_t end; (end = buffer.find('\n')) != std::string::npos; buffer.erase(0, end + 1))
						Handle(buffer.substr(0, end));
				}
				CloseHandle(overlapped.hEvent);
				{
					std::lock_guard write(g_writing);
					g_pipe = INVALID_HANDLE_VALUE;
				}
				CloseHandle(pipe);
				std::lock_guard lock(g_lock);
				g_connected = false;
				g_haveFriends = false;
				g_friends.clear();
				g_me.clear();
			}
		}

		// --- the menu

		bool InGame()
		{
			return *General::GameLoaded == 1 && *General::LobbyCheck != 0 && *General::CurrentGamemode == -1 && UtilsGlobal::getplayer();
		}

		bool Hosting()
		{
			const uintptr_t session = Gamespy::get_pc_session();
			return session && Gamespy::isSessionCoop(session);
		}

		const char* StatusText(int status) { return status == 2 ? "Playing" : status == 1 ? "Online" : "Offline"; }

		// The open tab's rows; friends: the invites waiting, then the friends.
		void MakeRows()
		{
			std::vector<Row> rows;
			std::string empty;
			if (g_tab == 0) {
				std::lock_guard lock(g_lock);
				const DWORD now = GetTickCount();
				g_invites.erase(std::remove_if(g_invites.begin(), g_invites.end(), [&](const Invite& i) { return now - i.at > InviteMs; }), g_invites.end());
				for (const Invite& invite : g_invites)
					rows.push_back({ invite.name + " invited you", "Join", Accent });
				for (const Friend& f : g_friends)
					rows.push_back({ f.name, StatusText(f.status), f.status == 2 ? Accent : f.status == 1 ? Green : Faint, false, f.status == 0 });
				if (!g_connected) empty = "Open the Stilwater launcher to see your friends here.";
				else if (g_me.empty()) empty = "Sign in in the Stilwater launcher to see your friends here.";
				else if (rows.empty()) empty = "No friends yet. Add them on the launcher's Friends page.";
			}
			else if (g_tab == 2) {
				for (int i = 0; i < Trainer::CheatCount(); i++) {
					const std::string label = Trainer::CheatLabel(i);
					const size_t tab = label.find('\t');
					rows.push_back({ label.substr(0, tab), tab == std::string::npos ? "" : label.substr(tab + 1) });
				}
				if (rows.empty()) empty = "The game's cheats show up here once a save is loaded.";
			}
			else {
				for (int i = 0; i < Trainer::Count(); i++) {
					const std::string label = Trainer::Label(i);
					const size_t tab = label.find('\t');
					rows.push_back({ label.substr(0, tab), tab == std::string::npos ? "" : label.substr(tab + 1), 0, Trainer::CanAdjust(i) });
				}
			}
			std::lock_guard lock(g_lock);
			g_rows = std::move(rows);
			g_empty = empty;
		}

		void Activate()
		{
			if (g_tab == 1) {
				Trainer::Activate(g_selected);
				return;
			}
			if (g_tab == 2) {
				const std::string why = Trainer::CheatActivate(g_selected);
				if (!why.empty()) AddNote(why, "");
				return;
			}
			int invites, friendId = 0, status = 0, inviteId = 0;
			std::string name;
			{
				std::lock_guard lock(g_lock);
				invites = (int)g_invites.size();
				if (g_selected < invites) {
					inviteId = g_invites[g_selected].id;
					name = g_invites[g_selected].name;
				}
				else if (g_selected - invites < (int)g_friends.size()) {
					const Friend& f = g_friends[g_selected - invites];
					friendId = f.id;
					status = f.status;
					name = f.name;
				}
			}
			if (inviteId) {
				Send(std::string("join") + Field + std::to_string(inviteId));
				return;
			}
			if (!friendId) return;
			if (status == 0) {
				AddNote(name + " is offline", "Invites reach friends who are online.");
				return;
			}
			Send(std::string("invite") + Field + std::to_string(friendId));
			if (!Hosting())
				AddNote("Host co-op so " + name + " can join", "Pause > Co-op > host an online game.");
		}

		// --- mouse: while the menu is open the game's mouse movement (written by its input update at
		// 0x00C1F414/1C, wheel at 0x00C1F435) moves our cursor instead of the camera.
		std::atomic<int> g_mouseX{ 0 }, g_mouseY{ 0 }, g_wheel{ 0 };
		SafetyHookMid g_mouseHook, g_wheelHook;
		float g_cursorX = 0, g_cursorY = 0;           // pixels
		bool g_clickWas = false, g_dragging = false;
		float g_dragX = 0, g_dragY = 0;
		int g_panelX = 80, g_panelY = 120;            // at 1080 pixels high

		void HookMouse()
		{
			g_mouseHook = safetyhook::create_mid(0x00C1F421, [](SafetyHookContext&) {
				if (!g_open) return;
				g_mouseX += *reinterpret_cast<int32_t*>(0x0234F45C);
				g_mouseY += *reinterpret_cast<int32_t*>(0x0234F458);
				*reinterpret_cast<int32_t*>(0x0234F45C) = 0;
				*reinterpret_cast<int32_t*>(0x0234F458) = 0;
			});
			g_wheelHook = safetyhook::create_mid(0x00C1F43B, [](SafetyHookContext&) {
				if (!g_open) return;
				g_wheel += *reinterpret_cast<int32_t*>(0x0234EA34);
				*reinterpret_cast<int32_t*>(0x0234EA34) = 0;
			});
		}

		// The panel's layout, in pixels, for the screen the overlay last drew on.
		struct Layout
		{
			float s, x, y, w, header, rowH, listTop, h;
			int first, shown;
			float tabX[3], tabW[3];
		};
		constexpr int VisibleRows = 10;
		constexpr int TabCount = 3;
		constexpr const char* Tabs[TabCount] = { "FRIENDS", "TRAINER", "CHEATS" };

		Layout MakeLayout()
		{
			Layout l{};
			l.s = std::max(0.5f, Overlay::Scale());
			l.w = 410 * l.s;
			l.header = 46 * l.s;
			l.rowH = 33 * l.s;
			const int count = (int)g_rows.size();
			l.first = g_first = std::clamp(g_first, 0, std::max(0, count - VisibleRows));
			l.shown = std::min(count - l.first, VisibleRows);
			l.h = l.header + 12 * l.s + std::max(l.shown, 1) * l.rowH + 40 * l.s;
			const float width = (float)std::max(Overlay::Width(), 640), height = (float)std::max(Overlay::Height(), 480);
			l.x = std::clamp(g_panelX * l.s, 0.0f, width - l.w);
			l.y = std::clamp(g_panelY * l.s, 0.0f, height - l.h);
			l.listTop = l.y + l.header + 10 * l.s;
			float right = l.x + l.w - 14 * l.s;
			for (int t = TabCount - 1; t >= 0; t--) {
				l.tabW[t] = Overlay::TextWidth(Tabs[t], Overlay::Font::Heading);
				l.tabX[t] = right - l.tabW[t];
				right = l.tabX[t] - 14 * l.s;
			}
			return l;
		}

		// Player controls off while the menu is open, so keys and clicks don't move the avatar; the
		// game keeps running (co-op couldn't pause anyway).
		void SetControls(bool on)
		{
			General::LuaExecute(on ? "player_controls_enable(LOCAL_PLAYER or \"#PLAYER1#\")"
				: "player_controls_disable(LOCAL_PLAYER or \"#PLAYER1#\")");
		}

		// Scrolls just enough to show the selected row (after the arrow keys move it).
		void ShowSelected()
		{
			if (g_selected < g_first) g_first = g_selected;
			if (g_selected >= g_first + VisibleRows) g_first = g_selected - VisibleRows + 1;
		}

		void Open()
		{
			g_open = true;
			g_selected = 0;
			g_first = 0;
			g_mouseX = 0;
			g_mouseY = 0;
			g_wheel = 0;
			if (g_tab == 1) Trainer::Opened();
			SetControls(false);
			std::lock_guard lock(g_lock);
			const Layout l = MakeLayout();
			g_cursorX = l.x + l.w / 2;
			g_cursorY = l.y + l.header / 2;
		}

		void Close()
		{
			g_open = false;
			g_dragging = false;
			SetControls(true);
		}

		void SwitchTab(int tab)
		{
			if (tab == g_tab) return;
			g_tab = tab;
			g_selected = 0;
			g_first = 0;
			if (g_tab == 1) Trainer::Opened();
			MakeRows();
		}

		// Mouse: hover selects, a click uses (on a trainer value, its left or right half changes it),
		// the title bar drags the panel, the wheel scrolls.
		void HandleMouse(int count)
		{
			const float width = (float)Overlay::Width(), height = (float)Overlay::Height();
			if (width <= 0 || height <= 0) return;
			const int dx = g_mouseX.exchange(0), dy = g_mouseY.exchange(0), wheel = g_wheel.exchange(0);
			g_cursorX = std::clamp(g_cursorX + dx, 0.0f, width - 1);
			g_cursorY = std::clamp(g_cursorY + dy, 0.0f, height - 1);
			const bool down = General::IsSRFocused() && (GetAsyncKeyState(VK_LBUTTON) & 0x8000);
			const bool clicked = down && !g_clickWas;
			g_clickWas = down;
			Layout l;
			{
				std::lock_guard lock(g_lock);
				l = MakeLayout();
			}

			if (g_dragging) {
				if (!down) {
					g_dragging = false;
					GameConfig::SetValue("Stilwater", "MenuX", (uint32_t)g_panelX);
					GameConfig::SetValue("Stilwater", "MenuY", (uint32_t)g_panelY);
				}
				else {
					g_panelX = std::max(0, (int)((g_cursorX - g_dragX) / l.s));
					g_panelY = std::max(0, (int)((g_cursorY - g_dragY) / l.s));
				}
				return;
			}
			if (wheel && count > VisibleRows) {
				// One row per notch (120 a notch, or 1 on some mice); the row under the cursor stays selected.
				const int notches = std::max(1, std::abs(wheel) / 120);
				g_first = std::clamp(g_first + (wheel > 0 ? -notches : notches), 0, count - VisibleRows);
				std::lock_guard lock(g_lock);
				l = MakeLayout();
			}

			const bool inPanel = g_cursorX >= l.x && g_cursorX < l.x + l.w && g_cursorY >= l.y && g_cursorY < l.y + l.h;
			if (!inPanel) return;
			if (g_cursorY < l.y + l.header) {
				if (!clicked) return;
				for (int t = 0; t < TabCount; t++)
					if (g_cursorX >= l.tabX[t] - 6 * l.s && g_cursorX < l.tabX[t] + l.tabW[t] + 6 * l.s) {
						SwitchTab(t);
						return;
					}
				g_dragging = true;
				g_dragX = g_cursorX - l.x;
				g_dragY = g_cursorY - l.y;
				return;
			}
			const int row = (int)std::floor((g_cursorY - l.listTop) / l.rowH);
			if (row < 0 || row >= l.shown) return;
			if (dx || dy || wheel || clicked) g_selected = l.first + row;
			if (!clicked) return;
			const bool adjustable = g_tab == 1 && Trainer::CanAdjust(g_selected);
			if (adjustable && g_cursorX >= l.x + l.w * 0.55f)
				Trainer::Adjust(g_selected, g_cursorX < l.x + l.w * 0.775f ? -1 : 1);
			else
				Activate();
		}

		// --- drawing (from the Present hook)

		void DrawNotes(float s, int width)
		{
			const DWORD now = GetTickCount();
			const float w = 400 * s, x = width - w - 28 * s;
			float y = 28 * s;
			for (const Note& note : g_notes) {
				const DWORD age = now - note.at;
				const float fade = age > NoteMs - 400 ? (NoteMs - age) / 400.0f : 1.0f;
				auto alpha = [fade](uint32_t c) { return ((uint32_t)(((c >> 24) & 0xFF) * std::clamp(fade, 0.0f, 1.0f)) << 24) | (c & 0xFFFFFF); };
				const float h = (note.text.empty() ? 46 : 66) * s;
				Overlay::RoundRect(x, y, w, h, 7 * s, alpha(Panel));
				Overlay::RoundRect(x + 7 * s, y + 12 * s, 3 * s, h - 24 * s, 1.5f * s, alpha(Accent));
				Overlay::Text(x + 22 * s, y + 12 * s, note.title, Overlay::Font::Body, alpha(Text));
				if (!note.text.empty())
					Overlay::Text(x + 22 * s, y + 38 * s, note.text, Overlay::Font::Small, alpha(Muted));
				y += h + 8 * s;
			}
		}

		void DrawCursor(float s)
		{
			// An arrow made of rows of pixels, its dark outline first.
			const float px = std::max(1.0f, std::round(1.5f * s));
			for (int pass = 0; pass < 2; pass++) {
				const uint32_t colour = pass == 0 ? 0xFF000000 : 0xFFFFFFFF;
				const float grow = pass == 0 ? px : 0;
				for (int i = 0; i < 12; i++) {
					const float rowW = (i < 9 ? i + 1 : 12 - i) * px;
					Overlay::Rect(g_cursorX - grow, g_cursorY + i * px - grow, rowW + 2 * grow, px + 2 * grow, colour);
				}
			}
		}

		void DrawMenu()
		{
			const Layout l = MakeLayout();
			const float s = l.s;
			const float r = 8 * s;
			Overlay::RoundRect(l.x + 6 * s, l.y + 8 * s, l.w, l.h, r, 0x50000000);    // shadow
			Overlay::RoundRect(l.x - 1, l.y - 1, l.w + 2, l.h + 2, r + 1, Line);
			Overlay::RoundRect(l.x, l.y, l.w, l.h, r, Panel);
			Overlay::RoundRect(l.x, l.y, l.w, l.header, r, 0xFF0B0B0D);               // title bar: rounded top,
			Overlay::Rect(l.x, l.y + l.header - r, l.w, r, 0xFF0B0B0D);              // square bottom
			Overlay::Rect(l.x, l.y + l.header, l.w, 1, Line);
			const float headH = Overlay::LineHeight(Overlay::Font::Heading);
			Overlay::Text(l.x + 14 * s, l.y + (l.header - headH) / 2, "STILWATER", Overlay::Font::Heading, Text);
			for (int t = 0; t < TabCount; t++) {
				Overlay::Text(l.tabX[t], l.y + (l.header - headH) / 2, Tabs[t], Overlay::Font::Heading, t == g_tab ? Text : Muted);
				if (t == g_tab) Overlay::Rect(l.tabX[t], l.y + l.header - 3 * s, l.tabW[t], 2 * s, Accent);
			}

			if (g_rows.empty())
				Overlay::Text(l.x + 14 * s, l.listTop + 8 * s, g_empty, Overlay::Font::Small, Muted);
			const float bodyH = Overlay::LineHeight(Overlay::Font::Body), smallH = Overlay::LineHeight(Overlay::Font::Small);
			for (int i = 0; i < l.shown; i++) {
				const Row& row = g_rows[l.first + i];
				const bool on = l.first + i == g_selected;
				const float y = l.listTop + i * l.rowH;
				if (on) {
					Overlay::RoundRect(l.x + 6 * s, y, l.w - 12 * s, l.rowH - 2 * s, 5 * s, Selected);
					Overlay::RoundRect(l.x + 8 * s, y + 7 * s, 3 * s, l.rowH - 16 * s, 1.5f * s, Accent);
				}
				float lx = l.x + 18 * s;
				if (row.dot) {
					Overlay::RoundRect(lx, y + (l.rowH - 2 * s) / 2 - 4 * s, 8 * s, 8 * s, 4 * s, row.dot);
					lx += 16 * s;
				}
				Overlay::Text(lx, y + (l.rowH - 2 * s - bodyH) / 2, row.label, Overlay::Font::Body, row.dim ? Muted : Text);
				std::string value = row.value;
				if (on && row.adjustable) value = "<  " + value + "  >";
				if (!value.empty())
					Overlay::Text(l.x + l.w - 16 * s - Overlay::TextWidth(value, Overlay::Font::Small), y + (l.rowH - 2 * s - smallH) / 2,
						value, Overlay::Font::Small, on ? Text : Muted);
			}
			const int count = (int)g_rows.size();
			if (count > VisibleRows) {
				// Where the visible rows sit in the whole list.
				const float trackH = VisibleRows * l.rowH;
				Overlay::Rect(l.x + l.w - 4 * s, l.listTop + trackH * l.first / count, 2 * s, trackH * VisibleRows / count, Faint);
			}
			Overlay::Rect(l.x, l.y + l.h - 34 * s, l.w, 1, Line);
			const std::string hint = g_tab == 0 ? "Click to invite or join   |   Insert to close" : "Click to use   |   Insert to close";
			Overlay::Text(l.x + 14 * s, l.y + l.h - 34 * s + (34 * s - Overlay::LineHeight(Overlay::Font::Small)) / 2, hint, Overlay::Font::Small, Faint);
			DrawCursor(s);
		}

		void Draw()
		{
			std::lock_guard lock(g_lock);
			DrawNotes(Overlay::Scale(), Overlay::Width());
			if (g_open) DrawMenu();
		}
	}

	void Init()
	{
		g_key = (unsigned char)GameConfig::GetValue("Stilwater", "MenuKey", VK_INSERT,
			"Key that opens the Stilwater menu (friends, invites, trainer), as a Windows virtual-key code (0x2D = Insert).");
		g_altKey = (unsigned char)GameConfig::GetValue("Stilwater", "MenuKey2", 0,
			"Another key that opens it, as a virtual-key code (0 for none; M opens the map).");
		g_panelX = (int)GameConfig::GetValue("Stilwater", "MenuX", 80, "Where the Stilwater menu sits (drag its title bar to move it).");
		g_panelY = (int)GameConfig::GetValue("Stilwater", "MenuY", 120);
		HookMouse();
		std::thread(PipeThread).detach();
	}

	void Update()
	{
		Overlay::Init();
		if (!InGame()) {
			if (g_open) Close();
		}
		else if (IsKeyPressed(g_key, false) || (g_altKey && IsKeyPressed(g_altKey, false)))
			g_open ? Close() : Open();

		if (g_open) {
			MakeRows();
			int count;
			{
				std::lock_guard lock(g_lock);
				count = (int)g_rows.size();
			}
			const bool adjustable = g_tab == 1 && g_selected < count && Trainer::CanAdjust(g_selected);
			if (IsKeyPressed(VK_TAB, false) || (!adjustable && IsKeyPressed(VK_RIGHT, false)))
				SwitchTab((g_tab + 1) % TabCount);
			else if (!adjustable && IsKeyPressed(VK_LEFT, false))
				SwitchTab((g_tab + TabCount - 1) % TabCount);
			else if (count > 0) {
				if (IsKeyPressed(VK_UP, false)) g_selected = (g_selected + count - 1) % count;
				if (IsKeyPressed(VK_DOWN, false)) g_selected = (g_selected + 1) % count;
				g_selected = std::min(g_selected, count - 1);
				ShowSelected();
				if (adjustable && IsKeyPressed(VK_LEFT, false)) Trainer::Adjust(g_selected, -1);
				if (adjustable && IsKeyPressed(VK_RIGHT, false)) Trainer::Adjust(g_selected, 1);
				if (IsKeyPressed(VK_RETURN, false)) Activate();
			}
			{
				std::lock_guard lock(g_lock);
				count = (int)g_rows.size();
			}
			HandleMouse(count);
			if (IsKeyPressed(VK_BACK, false)) Close();
			if (g_open) MakeRows();
		}

		bool notes;
		{
			std::lock_guard lock(g_lock);
			const DWORD now = GetTickCount();
			while (!g_notes.empty() && now - g_notes.front().at > NoteMs) g_notes.pop_front();
			notes = !g_notes.empty();
		}
		Overlay::SetDraw(g_open || notes ? &Draw : nullptr);
	}
}
