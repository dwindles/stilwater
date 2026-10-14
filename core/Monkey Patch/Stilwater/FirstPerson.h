#pragma once

// Stilwater: first-person camera (on foot and in vehicles), toggled in game.
namespace FirstPerson
{
	void Init();   // reads [Stilwater] FirstPersonKey / heights, installs the camera hooks
	void Update(); // per frame, from the game loop: toggle and eye-height keys
}
