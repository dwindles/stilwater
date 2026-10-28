#pragma once

// Saves are never marked as cheated, whatever is used (cheat codes, the trainer, teleporting, the
// Lua console).
namespace CheatFlag
{
	void Init();   // after Debug::Init
	void Update(); // per frame, from the game loop
}
