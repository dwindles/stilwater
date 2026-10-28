#pragma once

#include <string>

// Stilwater trainer: the cheats on the Insert menu's Trainer tab (InviteMenu.cpp shows them).
// Labels are "Name" or "Name\tValue".
namespace Trainer
{
	void Init();
	void Update();                         // per frame, from the game loop (vehicle horns)
	void Opened();                         // the tab was opened: loads the vehicle list
	int Count();
	std::string Label(int item);
	bool CanAdjust(int item);              // takes left/right
	void Activate(int item);
	void Adjust(int item, int direction);

	// The game's own cheats (what the phone's cheat menu has). Labels as above.
	int CheatCount();
	std::string CheatLabel(int index);
	std::string CheatActivate(int index);  // returns why it couldn't, or ""
}
