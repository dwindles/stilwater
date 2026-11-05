#pragma once

// More copies of the game on the same PC, for testing co-op past two players with fewer people
// (the launcher's --second-copy, --third-copy and --fourth-copy start them with STILWATER_COPY=2..4).
namespace SecondCopy
{
	int Number();               // which copy this is (1 = the usual one)
	bool Active();              // this game is an extra copy
	const char* IniName();      // juiced.ini, or the copy's own
	const char* LogName();      // debug.txt, or the copy's own
	void Init();                // at startup, before the game's WinMain runs
}
