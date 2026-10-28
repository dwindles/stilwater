#pragma once

#include <cstdint>
#include <string>

// Stilwater's own 2D drawing on top of the game: panels and text in real fonts, drawn just before
// each frame is shown (IDirect3DDevice9::Present). Coordinates are in pixels of the back buffer.
namespace Overlay
{
	enum class Font { Body, Small, Title, Heading };

	void Init();                                 // hooks Present once the game's device exists (call per frame)
	void SetDraw(void (*draw)());                // what to draw each frame (from the Present hook)

	// Only valid inside the draw callback.
	int Width();
	int Height();
	float Scale();                               // the back buffer's height / 1080
	void Rect(float x, float y, float w, float h, uint32_t argb);
	void RoundRect(float x, float y, float w, float h, float radius, uint32_t argb);
	float Text(float x, float y, const std::string& utf8, Font font, uint32_t argb);   // returns the width
	float TextWidth(const std::string& utf8, Font font);
	float LineHeight(Font font);
}
