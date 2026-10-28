#pragma once

// Stilwater: forwards the game's ports through the router (UPnP) while it runs, so co-op friends
// can join a game hosted behind a router that only lets traffic in on forwarded ports.
namespace CoopPorts
{
	void Init(); // reads [Stilwater] UPnP; starts the background forwarding thread
}
