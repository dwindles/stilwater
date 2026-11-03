#pragma once

// The game's own co-op with more than two players ([Stilwater] MaxCoopPlayers, 2 = the game's own).
namespace CoopSize
{
	void Init();     // at startup, before the game sets up its memory
	int Players();   // the co-op player cap in use
	void Update();   // every frame: on the host, missions' REMOTE_PLAYER actions go to every player
}
