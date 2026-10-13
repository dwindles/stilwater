// Stilwater runtime: loaded into SR2_pc.exe by stilwater-loader.
// Milestone 0 only observes the game and logs what it finds; no hooks yet.

#include <windows.h>
#include <psapi.h>

#include <cstdint>

#include "log.h"

namespace {

HMODULE g_self = nullptr;

// Addresses are for the unencrypted Steam/GOG build that Juiced Patch targets.
constexpr uintptr_t kWinMain = 0x00520BA0;
constexpr uint32_t kWinMainPrologue = 0x83EC8B55;  // push ebp; mov ebp, esp; sub esp, ...
constexpr uintptr_t kDisplaySettings = 0x01F7A9A0; // width, height, ?, fullscreen byte at +0x0C

struct WindowSearch {
  DWORD pid;
  HWND hwnd;
};

BOOL CALLBACK find_game_window(HWND hwnd, LPARAM param) {
  auto* search = reinterpret_cast<WindowSearch*>(param);
  DWORD pid = 0;
  GetWindowThreadProcessId(hwnd, &pid);
  if (pid == search->pid && IsWindowVisible(hwnd) && GetWindow(hwnd, GW_OWNER) == nullptr) {
    search->hwnd = hwnd;
    return FALSE;
  }
  return TRUE;
}

void log_process() {
  auto* base = reinterpret_cast<uint8_t*>(GetModuleHandleW(nullptr));
  auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
  auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
  wchar_t exe[MAX_PATH];
  GetModuleFileNameW(nullptr, exe, MAX_PATH);
  logging::write("game: %ls", exe);
  logging::write("image base: 0x%08X  large address aware: %s", reinterpret_cast<uintptr_t>(base),
                 (nt->FileHeader.Characteristics & IMAGE_FILE_LARGE_ADDRESS_AWARE) ? "yes" : "no");

  const uint32_t prologue = *reinterpret_cast<const uint32_t*>(kWinMain);
  logging::write("build check: WinMain prologue 0x%08X (%s)", prologue,
                 prologue == kWinMainPrologue ? "supported unencrypted build" : "UNKNOWN or encrypted build");
}

void log_modules() {
  HMODULE juiced = GetModuleHandleW(L"DFEngine.dll");
  const bool has_api = juiced && GetProcAddress(juiced, "RegisterVintLuaHookString");
  logging::write("Juiced Patch (DFEngine.dll): %s%s", juiced ? "loaded" : "not loaded",
                 has_api ? ", JuicedAPI available" : "");
  logging::write("d3d9.dll: %s", GetModuleHandleW(L"d3d9.dll") ? "loaded" : "not loaded yet");
}

void log_window() {
  WindowSearch search{GetCurrentProcessId(), nullptr};
  for (int i = 0; i < 240 && !search.hwnd; ++i) {
    Sleep(500);
    EnumWindows(find_game_window, reinterpret_cast<LPARAM>(&search));
  }
  if (!search.hwnd) {
    logging::write("game window: not found after 120s");
    return;
  }
  Sleep(5000);  // let Juiced apply its window style
  RECT rect{}, client{};
  GetWindowRect(search.hwnd, &rect);
  GetClientRect(search.hwnd, &client);
  const LONG style = GetWindowLongW(search.hwnd, GWL_STYLE);
  logging::write("game window: %ldx%ld at (%ld,%ld), client %ldx%ld, %s", rect.right - rect.left,
                 rect.bottom - rect.top, rect.left, rect.top, client.right, client.bottom,
                 (style & WS_POPUP) && !(style & WS_CAPTION) ? "borderless" : "has border");

  const auto* settings = reinterpret_cast<const uint32_t*>(kDisplaySettings);
  const auto fullscreen = *reinterpret_cast<const uint8_t*>(kDisplaySettings + 0x0C);
  logging::write("display settings: %ux%u, fullscreen=%u", settings[0], settings[1], fullscreen);
}

DWORD WINAPI main_thread(LPVOID) {
  logging::open(g_self);
  logging::write("Stilwater runtime loaded (milestone 0)");
  log_process();
  log_modules();
  log_window();
  logging::write("startup checks done");
  return 0;
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    g_self = module;
    DisableThreadLibraryCalls(module);
    // Never do real work under the loader lock.
    if (HANDLE thread = CreateThread(nullptr, 0, main_thread, nullptr, 0, nullptr)) CloseHandle(thread);
  } else if (reason == DLL_PROCESS_DETACH) {
    logging::close();
  }
  return TRUE;
}
