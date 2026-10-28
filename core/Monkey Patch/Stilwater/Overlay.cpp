// Overlay.cpp (Stilwater)
// Draws Stilwater's own UI (the Insert menu, notifications) over the finished frame. The game's
// device is at 0x0252A2D0; once it exists, IDirect3DDevice9::Present (vtable 17) and its implicit
// swap chain's Present (vtable 3) are hooked, whichever the game calls (DXVK's device Present also
// goes through the swap chain's, so a frame is drawn on only once). Text comes from a font atlas made
// with GDI (Windows' own fonts, CP1252 characters) for the back buffer's height; panels use a white
// block in the same texture. The game's render state is saved and put back around the drawing.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

#include <safetyhook.hpp>

#include "Overlay.h"
#include "../FileLogger.h"

namespace Overlay
{
	namespace
	{
		constexpr uintptr_t DeviceAddress = 0x0252A2D0;
		constexpr int AtlasSize = 1024;
		constexpr DWORD Fvf = D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1;

		struct Vertex { float x, y, z, rhw; DWORD color; float u, v; };
		struct Glyph { float u0, v0, u1, v1; int width, offset, advance; };
		struct FontData { Glyph glyphs[256]; int height = 0; };

		SafetyHookInline g_devicePresent, g_chainPresent;
		void (*g_draw)() = nullptr;
		bool g_drawing = false;            // inside our Present: the swap chain's must not draw again
		IDirect3DDevice9* g_device = nullptr;
		IDirect3DTexture9* g_atlas = nullptr;
		int g_atlasHeight = 0, g_width = 0, g_height = 0;
		FontData g_fonts[4];
		std::vector<Vertex> g_vertices;

		struct FontSpec { const wchar_t* face; int size; int weight; };
		// Body, Small, Title, Heading at 1080 pixels high.
		constexpr FontSpec Specs[4] = {
			{ L"Segoe UI", 19, FW_NORMAL },
			{ L"Segoe UI", 17, FW_NORMAL },
			{ L"Bahnschrift SemiBold Condensed", 38, FW_NORMAL },
			{ L"Bahnschrift SemiBold Condensed", 23, FW_NORMAL },
		};

		bool BuildAtlas(IDirect3DDevice9* device, int height)
		{
			if (g_atlas) { g_atlas->Release(); g_atlas = nullptr; }
			const float scale = height / 1080.0f;
			BITMAPINFO info{};
			info.bmiHeader = { sizeof(BITMAPINFOHEADER), AtlasSize, -AtlasSize, 1, 32, BI_RGB };
			HDC dc = CreateCompatibleDC(nullptr);
			void* bits = nullptr;
			HBITMAP bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
			if (!bitmap || !bits) { DeleteDC(dc); return false; }
			HGDIOBJ oldBitmap = SelectObject(dc, bitmap);
			auto* pixels = static_cast<uint32_t*>(bits);
			std::memset(pixels, 0, AtlasSize * AtlasSize * 4);
			for (int y = 0; y < 4; y++)
				for (int x = 0; x < 4; x++)
					pixels[y * AtlasSize + x] = 0xFFFFFFFF;       // the white block for panels
			SetBkMode(dc, TRANSPARENT);
			SetTextColor(dc, RGB(255, 255, 255));

			int x = 6, y = 0, row = 4;
			for (int f = 0; f < 4; f++) {
				HFONT font = CreateFontW(-std::max(8, (int)(Specs[f].size * scale)), 0, 0, 0, Specs[f].weight, FALSE, FALSE, FALSE,
					DEFAULT_CHARSET, OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, DEFAULT_PITCH, Specs[f].face);
				HGDIOBJ oldFont = SelectObject(dc, font);
				TEXTMETRICW metrics{};
				GetTextMetricsW(dc, &metrics);
				g_fonts[f].height = metrics.tmHeight;
				for (int c = 32; c < 256; c++) {
					char byte = (char)c;
					wchar_t ch = L'?';
					MultiByteToWideChar(1252, 0, &byte, 1, &ch, 1);
					ABC abc{};
					if (!GetCharABCWidthsW(dc, ch, ch, &abc)) {
						SIZE size{};
						GetTextExtentPoint32W(dc, &ch, 1, &size);
						abc = { 0, (UINT)size.cx, 0 };
					}
					const int cell = (int)abc.abcB + 2;
					if (x + cell >= AtlasSize) { x = 0; y += row + 1; row = 0; }
					if (y + metrics.tmHeight >= AtlasSize) break;
					TextOutW(dc, x + 1 - abc.abcA, y, &ch, 1);
					Glyph& g = g_fonts[f].glyphs[c];
					g = { (float)x / AtlasSize, (float)y / AtlasSize, (float)(x + cell) / AtlasSize,
						  (float)(y + metrics.tmHeight) / AtlasSize, cell, abc.abcA - 1, abc.abcA + (int)abc.abcB + abc.abcC };
					x += cell + 1;
					row = std::max(row, (int)metrics.tmHeight);
				}
				SelectObject(dc, oldFont);
				DeleteObject(font);
				x = 0; y += row + 1; row = 0;
			}
			GdiFlush();

			bool ok = SUCCEEDED(device->CreateTexture(AtlasSize, AtlasSize, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &g_atlas, nullptr));
			D3DLOCKED_RECT locked{};
			if (ok && SUCCEEDED(g_atlas->LockRect(0, &locked, nullptr, 0))) {
				for (int row = 0; row < AtlasSize; row++) {
					auto* out = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(locked.pBits) + row * locked.Pitch);
					for (int col = 0; col < AtlasSize; col++)
						out[col] = ((pixels[row * AtlasSize + col] & 0xFF) << 24) | 0x00FFFFFF;   // coverage -> alpha
				}
				g_atlas->UnlockRect(0);
			}
			else ok = false;
			SelectObject(dc, oldBitmap);
			DeleteObject(bitmap);
			DeleteDC(dc);
			if (!ok && g_atlas) { g_atlas->Release(); g_atlas = nullptr; }
			Logger::TypedLog(CHN_DLL, "Overlay: font atlas for {} pixels high {}.\n", height, ok ? "made" : "failed");
			return ok;
		}

		void Quad(float x, float y, float w, float h, float u0, float v0, float u1, float v1, uint32_t color)
		{
			x -= 0.5f; y -= 0.5f;
			const Vertex a{ x, y, 0, 1, color, u0, v0 }, b{ x + w, y, 0, 1, color, u1, v0 },
				c{ x, y + h, 0, 1, color, u0, v1 }, d{ x + w, y + h, 0, 1, color, u1, v1 };
			g_vertices.insert(g_vertices.end(), { a, b, c, b, d, c });
		}

		void Flush()
		{
			if (g_vertices.empty()) return;
			g_device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, (UINT)(g_vertices.size() / 3), g_vertices.data(), sizeof(Vertex));
			g_vertices.clear();
		}

		// UTF-8 to the atlas's CP1252 bytes ('?' for anything else).
		std::string ToAtlas(const std::string& utf8)
		{
			int wide = MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), nullptr, 0);
			std::wstring text(wide, L'\0');
			MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), text.data(), wide);
			int size = WideCharToMultiByte(1252, 0, text.data(), wide, nullptr, 0, "?", nullptr);
			std::string out(size, '\0');
			WideCharToMultiByte(1252, 0, text.data(), wide, out.data(), size, "?", nullptr);
			return out;
		}

		void Render(IDirect3DDevice9* device)
		{
			if (!g_draw || g_drawing) return;
			g_drawing = true;
			IDirect3DSurface9* backBuffer = nullptr;
			IDirect3DSurface9* target = nullptr;
			IDirect3DStateBlock9* state = nullptr;
			if (SUCCEEDED(device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &backBuffer)) &&
				SUCCEEDED(device->CreateStateBlock(D3DSBT_ALL, &state))) {
				D3DSURFACE_DESC desc{};
				backBuffer->GetDesc(&desc);
				g_device = device;
				g_width = (int)desc.Width;
				g_height = (int)desc.Height;
				if (g_atlasHeight != g_height && BuildAtlas(device, g_height))
					g_atlasHeight = g_height;
				if (g_atlas) {
					device->GetRenderTarget(0, &target);
					device->SetRenderTarget(0, backBuffer);
					D3DVIEWPORT9 viewport{ 0, 0, desc.Width, desc.Height, 0, 1 };
					device->SetViewport(&viewport);
					device->SetVertexShader(nullptr);
					device->SetPixelShader(nullptr);
					device->SetFVF(Fvf);
					device->SetRenderState(D3DRS_ZENABLE, FALSE);
					device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
					device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
					device->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
					device->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
					device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
					device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
					device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
					device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
					device->SetRenderState(D3DRS_LIGHTING, FALSE);
					device->SetRenderState(D3DRS_FOGENABLE, FALSE);
					device->SetRenderState(D3DRS_STENCILENABLE, FALSE);
					device->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
					device->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
					device->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
					device->SetTexture(0, g_atlas);
					device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
					device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
					device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
					device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
					device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
					device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
					device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
					device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
					device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
					device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
					device->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
					device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
					device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
					device->SetSamplerState(0, D3DSAMP_SRGBTEXTURE, FALSE);
					if (SUCCEEDED(device->BeginScene())) {
						g_draw();
						Flush();
						device->EndScene();
					}
					g_vertices.clear();
					if (target) { device->SetRenderTarget(0, target); target->Release(); }
				}
				state->Apply();
			}
			if (state) state->Release();
			if (backBuffer) backBuffer->Release();
			g_drawing = false;
		}

		HRESULT __stdcall DevicePresent(IDirect3DDevice9* device, const RECT* source, const RECT* dest, HWND window, const RGNDATA* dirty)
		{
			Render(device);
			g_drawing = true;       // DXVK's device Present calls the swap chain's
			HRESULT result = g_devicePresent.unsafe_stdcall<HRESULT>(device, source, dest, window, dirty);
			g_drawing = false;
			return result;
		}

		HRESULT __stdcall ChainPresent(IDirect3DSwapChain9* chain, const RECT* source, const RECT* dest, HWND window, const RGNDATA* dirty, DWORD flags)
		{
			IDirect3DDevice9* device = nullptr;
			if (SUCCEEDED(chain->GetDevice(&device))) {
				Render(device);
				device->Release();
			}
			return g_chainPresent.unsafe_stdcall<HRESULT>(chain, source, dest, window, dirty, flags);
		}
	}

	void Init()
	{
		if (g_devicePresent) return;
		auto* device = *reinterpret_cast<IDirect3DDevice9**>(DeviceAddress);
		if (!device) return;
		void** vtable = *reinterpret_cast<void***>(device);
		g_devicePresent = safetyhook::create_inline(vtable[17], &DevicePresent);
		IDirect3DSwapChain9* chain = nullptr;
		if (SUCCEEDED(device->GetSwapChain(0, &chain)) && chain) {
			void** chainTable = *reinterpret_cast<void***>(chain);
			if (chainTable[3] != vtable[17])
				g_chainPresent = safetyhook::create_inline(chainTable[3], &ChainPresent);
			chain->Release();
		}
		Logger::TypedLog(CHN_DLL, "Overlay: hooked Present (device {}, swap chain {}).\n",
			(bool)g_devicePresent, (bool)g_chainPresent);
	}

	void SetDraw(void (*draw)()) { g_draw = draw; }
	int Width() { return g_width; }
	int Height() { return g_height; }
	float Scale() { return g_height / 1080.0f; }

	void Rect(float x, float y, float w, float h, uint32_t argb)
	{
		const float white = 2.0f / AtlasSize;
		Quad(x, y, w, h, white, white, white, white, argb);
	}

	void RoundRect(float x, float y, float w, float h, float radius, uint32_t argb)
	{
		radius = std::floor(std::min({ radius, w / 2, h / 2 }));
		if (radius < 1) { Rect(x, y, w, h, argb); return; }
		// The middle in one piece, the rounded top and bottom one pixel row at a time.
		Rect(x, y + radius, w, h - 2 * radius, argb);
		for (int i = 0; i < (int)radius; i++) {
			const float dy = radius - i - 0.5f;
			const float inset = std::round(radius - std::sqrt(std::max(0.0f, radius * radius - dy * dy)));
			Rect(x + inset, y + i, w - 2 * inset, 1, argb);
			Rect(x + inset, y + h - 1 - i, w - 2 * inset, 1, argb);
		}
	}

	float Text(float x, float y, const std::string& utf8, Font font, uint32_t argb)
	{
		const FontData& data = g_fonts[(int)font];
		const float start = x;
		for (unsigned char c : ToAtlas(utf8)) {
			if (c < 32) continue;
			const Glyph& g = data.glyphs[c];
			Quad(std::floor(x) + g.offset, std::floor(y), (float)g.width, (float)data.height, g.u0, g.v0, g.u1, g.v1, argb);
			x += g.advance;
		}
		return x - start;
	}

	float TextWidth(const std::string& utf8, Font font)
	{
		const FontData& data = g_fonts[(int)font];
		float width = 0;
		for (unsigned char c : ToAtlas(utf8))
			if (c >= 32) width += data.glyphs[c].advance;
		return width;
	}

	float LineHeight(Font font) { return (float)g_fonts[(int)font].height; }
}
