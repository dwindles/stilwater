// CoopPorts.cpp (Stilwater)
// Online co-op goes through OpenSpy (Patches/OpenSpy.cpp): the host lists its game on the master
// server and the joining player connects to the host directly, with GameSpy's NAT negotiation when
// the host is behind a router. That fails on routers that only let traffic in on forwarded ports,
// so while the game runs, every UDP port it has open (its game socket and GameSpy's query port,
// both chosen at run time) is forwarded to this PC through UPnP (Windows' NATUPnP). Forwards carry
// our description; ones left from an earlier session (the game can't remove them when it exits)
// are removed at start, and ones whose port closed are removed as we go.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <iphlpapi.h>
#include <natupnp.h>
#include <oleauto.h>

#include <set>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "CoopPorts.h"
#include "../FileLogger.h"
#include "../GameConfig.h"

#pragma comment(lib, "iphlpapi.lib")
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")

namespace CoopPorts
{
	namespace
	{
		constexpr wchar_t Description[] = L"Saints Row 2 (Stilwater)";
		constexpr DWORD PollMs = 5000;

		// The address this PC reaches the internet from (connecting a UDP socket sends nothing).
		std::wstring LocalAddress()
		{
			SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
			if (s == INVALID_SOCKET) return L"";
			sockaddr_in to{};
			to.sin_family = AF_INET;
			to.sin_port = htons(53);
			inet_pton(AF_INET, "8.8.8.8", &to.sin_addr);
			sockaddr_in me{};
			int length = sizeof(me);
			const bool ok = connect(s, reinterpret_cast<sockaddr*>(&to), sizeof(to)) == 0 &&
				getsockname(s, reinterpret_cast<sockaddr*>(&me), &length) == 0;
			closesocket(s);
			wchar_t text[INET_ADDRSTRLEN] = {};
			return ok && InetNtopW(AF_INET, &me.sin_addr, text, INET_ADDRSTRLEN) ? text : L"";
		}

		// The UDP ports this process has open (not loopback-only ones).
		std::set<unsigned short> GamePorts()
		{
			std::set<unsigned short> ports;
			DWORD size = 0;
			GetExtendedUdpTable(nullptr, &size, FALSE, AF_INET, UDP_TABLE_OWNER_PID, 0);
			std::vector<BYTE> buffer(size + 1024);
			size = static_cast<DWORD>(buffer.size());
			auto* table = reinterpret_cast<MIB_UDPTABLE_OWNER_PID*>(buffer.data());
			if (GetExtendedUdpTable(table, &size, FALSE, AF_INET, UDP_TABLE_OWNER_PID, 0) != NO_ERROR) return ports;
			const DWORD pid = GetCurrentProcessId();
			for (DWORD i = 0; i < table->dwNumEntries; i++)
			{
				const MIB_UDPROW_OWNER_PID& row = table->table[i];
				if (row.dwOwningPid == pid && row.dwLocalAddr != htonl(INADDR_LOOPBACK))
					ports.insert(ntohs(static_cast<u_short>(row.dwLocalPort)));
			}
			return ports;
		}

		void RemoveLeftovers(IStaticPortMappingCollection* maps)
		{
			IUnknown* unknown = nullptr;
			if (FAILED(maps->get__NewEnum(&unknown)) || !unknown) return;
			IEnumVARIANT* items = nullptr;
			unknown->QueryInterface(IID_IEnumVARIANT, reinterpret_cast<void**>(&items));
			unknown->Release();
			if (!items) return;
			std::vector<std::pair<long, std::wstring>> ours;
			VARIANT item;
			VariantInit(&item);
			while (items->Next(1, &item, nullptr) == S_OK)
			{
				IStaticPortMapping* map = nullptr;
				if (item.vt == VT_DISPATCH && item.pdispVal &&
					SUCCEEDED(item.pdispVal->QueryInterface(IID_IStaticPortMapping, reinterpret_cast<void**>(&map))))
				{
					BSTR description = nullptr, protocol = nullptr;
					long port = 0;
					map->get_Description(&description);
					map->get_Protocol(&protocol);
					map->get_ExternalPort(&port);
					if (description && wcscmp(description, Description) == 0)
						ours.emplace_back(port, protocol ? protocol : L"UDP");
					SysFreeString(description);
					SysFreeString(protocol);
					map->Release();
				}
				VariantClear(&item);
			}
			items->Release();
			for (const auto& [port, protocol] : ours)
			{
				BSTR p = SysAllocString(protocol.c_str());
				maps->Remove(port, p);
				SysFreeString(p);
			}
			if (!ours.empty()) Logger::TypedLog(CHN_DLL, "CoopPorts: removed {} forwards left from an earlier session.\n", ours.size());
		}

		void Run()
		{
			if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return;
			WSADATA wsa;
			WSAStartup(MAKEWORD(2, 2), &wsa);
			IUPnPNAT* nat = nullptr;
			if (FAILED(CoCreateInstance(CLSID_UPnPNAT, nullptr, CLSCTX_ALL, IID_IUPnPNAT, reinterpret_cast<void**>(&nat))) || !nat)
			{
				Logger::TypedLog(CHN_DLL, "CoopPorts: UPnP isn't available on this PC.\n");
				return;
			}
			// The collection is null until a UPnP router answers (or when there is none).
			IStaticPortMappingCollection* maps = nullptr;
			for (int tries = 0; tries < 6 && !maps; tries++)
			{
				nat->get_StaticPortMappingCollection(&maps);
				if (!maps) Sleep(PollMs);
			}
			if (!maps)
			{
				Logger::TypedLog(CHN_DLL, "CoopPorts: no UPnP router found; forward ports by hand to host co-op.\n");
				nat->Release();
				return;
			}
			RemoveLeftovers(maps);

			const std::wstring address = LocalAddress();
			BSTR udp = SysAllocString(L"UDP");
			BSTR description = SysAllocString(Description);
			BSTR client = SysAllocString(address.c_str());
			std::set<unsigned short> tried;
			for (;;)
			{
				const std::set<unsigned short> open = GamePorts();
				for (unsigned short port : open)
				{
					if (tried.count(port)) continue;
					tried.insert(port);    // a refused port isn't retried every pass
					IStaticPortMapping* map = nullptr;
					const HRESULT result = maps->Add(port, udp, port, client, VARIANT_TRUE, description, &map);
					if (SUCCEEDED(result) && map)
					{
						map->Release();
						Logger::TypedLog(CHN_DLL, "CoopPorts: forwarded UDP port {} to this PC.\n", port);
					}
					else
						Logger::TypedLog(CHN_DLL, "CoopPorts: the router refused to forward UDP port {} ({:#010x}).\n", port,
							static_cast<unsigned long>(result));
				}
				for (auto it = tried.begin(); it != tried.end();)
				{
					if (open.count(*it))
					{
						++it;
						continue;
					}
					maps->Remove(*it, udp);
					it = tried.erase(it);
				}
				Sleep(PollMs);
			}
		}
	}

	void Init()
	{
		if (!GameConfig::GetValue("Stilwater", "UPnP", 1,
			"Forward the game's ports through the router (UPnP) while it runs, so co-op friends can join you. 1 = on."))
			return;
		std::thread(Run).detach();
	}
}
