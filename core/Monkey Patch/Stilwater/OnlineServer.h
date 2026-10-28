#pragma once

// Stilwater: points the game's GameSpy services (accounts, friends, game list, NAT negotiation) at
// Stilwater Online, or leaves them on OpenSpy.
namespace OnlineServer
{
	void Init(); // reads [Stilwater] OnlineServer; hooks name lookups unless it says "openspy"
}
