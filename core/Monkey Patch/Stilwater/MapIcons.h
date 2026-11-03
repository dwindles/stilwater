#pragma once

#include <string>

// Map icons of our own at fixed places (interiors the game doesn't mark, like Club Koi), kept in
// Stilwater\map_icons.txt next to the launcher and shown on the minimap and the pause map.
namespace MapIcons
{
	void Init();                   // at startup: the icon list, the hook that places our icons
	void Update();                 // every frame: puts the icons on the map once a save is loaded
	std::string StyleName();       // the icon "Add map icon here" uses
	void CycleStyle(int direction);
	void AddHere();                // an icon where the player stands
	void RemoveNearest();          // the nearest of ours, within 30 m
	int Count();
}
