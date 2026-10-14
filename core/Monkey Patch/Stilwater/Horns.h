#pragma once
#include <string>

// Stilwater: pick the horn of the car you're in (all cars of that model), from the trainer.
// Choices are saved per model in juiced.ini [StilwaterHorns] and reapplied when you get in.
namespace Horns
{
	bool InVehicle();             // the player is in a vehicle with a horn we can change
	std::string CurrentName();    // its horn, for display ("" when not in a vehicle)
	void Cycle(int direction);    // switch to the previous/next horn and save the choice
	void Update();                // per frame: reapply saved choices to the current vehicle
}
