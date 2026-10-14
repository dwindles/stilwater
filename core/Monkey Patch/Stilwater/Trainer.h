#pragma once

// Stilwater trainer: an in-game cheat menu drawn with the game's debug text renderer.
namespace Trainer
{
	void Init();   // reads [Stilwater] TrainerKey
	void Update(); // per frame, from the game loop: input and actions
	void Draw();   // per frame, from the render hook
}
