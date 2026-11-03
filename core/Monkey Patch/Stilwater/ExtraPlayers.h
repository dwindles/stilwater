#pragma once

#include <string>

// Co-op past two players. The game's own co-op holds a host and one partner; everyone else who
// joins a Stilwater world gets a character in each other player's game that copies where they are
// and which way they face, sent through the host's game (UDP, [Stilwater] WorldPort). Every other
// player in the world gets a name tag over their head, in the colour and effect of their profile.
namespace ExtraPlayers
{
	void Init();                                         // at startup: settings, the world socket
	void Update();                                       // every frame, on the game's thread
	void Join(const std::string& address, const std::string& host);   // join the world hosted at address
	void Leave();
	void SetName(const std::string& name);               // our name, as other players see it
	void SetStyle(const std::string& style);             // our name tag's look: the profile's key=value;... (color, effect, crew)
	bool HasTags();                                      // whether there are name tags to draw
	void DrawTags();                                     // name tags over the other players' heads (inside Overlay's draw)
	bool Ghost();                                        // testing alone: a character copying you 3 s late
	void SetGhost(bool on);
	bool OwnTag();                                       // our own name tag over our head
	void SetOwnTag(bool on);
	std::string Status();                                // a line for the menu
}
