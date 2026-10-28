#pragma once

// Stilwater's Insert menu: friends (invite them, join their game when they invite you) and the
// trainer, drawn with Overlay, plus pop-up notifications. Friends and invites come from the launcher
// over a named pipe (launcher/GamePipe.cs).
namespace InviteMenu
{
	void Init();   // reads [Stilwater] MenuKey, starts talking to the launcher
	void Update(); // per frame, from the game loop: keys and the menu's state
}
