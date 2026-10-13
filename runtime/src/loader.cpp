// stilwater-loader <game exe> <runtime dll>
// Starts the game suspended with its own folder as the working directory, loads the
// runtime with LoadLibraryW on a remote thread, then lets the game run.
// Must be 32-bit so LoadLibraryW resolves to the same address as in the game.
// Exit codes: 0 ok (prints the game PID), 2 bad arguments, 3 CreateProcess failed, 4 injection failed.

#include <windows.h>

#include <cstdio>
#include <filesystem>
#include <string>

namespace {

int fail(int code, const wchar_t* what) {
  std::fwprintf(stderr, L"%ls failed (error %lu)\n", what, GetLastError());
  return code;
}

bool inject(HANDLE process, const std::wstring& dll) {
  const SIZE_T bytes = (dll.size() + 1) * sizeof(wchar_t);
  void* remote = VirtualAllocEx(process, nullptr, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
  if (!remote) return false;

  bool ok = false;
  if (WriteProcessMemory(process, remote, dll.c_str(), bytes, nullptr)) {
    auto* load_library = reinterpret_cast<LPTHREAD_START_ROUTINE>(
        GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW"));
    if (HANDLE thread = CreateRemoteThread(process, nullptr, 0, load_library, remote, 0, nullptr)) {
      WaitForSingleObject(thread, 60000);
      DWORD module = 0;  // low 32 bits of the HMODULE; 0 means LoadLibraryW failed
      ok = GetExitCodeThread(thread, &module) && module != 0 && module != STILL_ACTIVE;
      CloseHandle(thread);
    }
  }
  VirtualFreeEx(process, remote, 0, MEM_RELEASE);
  return ok;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    std::fwprintf(stderr, L"usage: stilwater-loader <game exe> <runtime dll>\n");
    return 2;
  }
  const auto exe = std::filesystem::absolute(argv[1]);
  const auto dll = std::filesystem::absolute(argv[2]);
  if (!std::filesystem::exists(exe) || !std::filesystem::exists(dll)) {
    std::fwprintf(stderr, L"game exe or runtime dll not found\n");
    return 2;
  }

  std::wstring command = L"\"" + exe.wstring() + L"\"";
  const std::wstring workdir = exe.parent_path().wstring();
  STARTUPINFOW si{sizeof(si)};
  PROCESS_INFORMATION pi{};
  if (!CreateProcessW(exe.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_SUSPENDED, nullptr,
                      workdir.c_str(), &si, &pi))
    return fail(3, L"CreateProcess");

  if (!inject(pi.hProcess, dll.wstring())) {
    const int code = fail(4, L"Loading the runtime");
    TerminateProcess(pi.hProcess, 1);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return code;
  }

  ResumeThread(pi.hThread);
  std::wprintf(L"%lu\n", pi.dwProcessId);
  CloseHandle(pi.hThread);
  CloseHandle(pi.hProcess);
  return 0;
}
