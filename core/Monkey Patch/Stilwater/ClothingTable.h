#pragma once

// Stores hold 512 items, a store item the clothing table lacks is left out instead of crashing, and
// what happens when the clothing table (customization_items.xtbl) loads is logged: the game's own XML
// errors, how many items loaded and whether the items in [Stilwater] CheckItems are among them.
namespace ClothingTable
{
	void Init();   // at startup, before the game loads its tables
}
