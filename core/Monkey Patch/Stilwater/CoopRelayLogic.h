#pragma once

#include <cstdint>

// How a joined player decides, for each other joined player, whether its packets for them go
// through the host (CoopRelay.cpp). Times are GetTickCount milliseconds; 0 = never.
namespace CoopRelay
{
	constexpr uint32_t Unheard = 3000;      // nothing from them directly for this long: through the host
	constexpr uint32_t ProbeEvery = 1000;   // once they relay too, a direct probe this often (saying whether we hear them)
	constexpr uint32_t HelloEvery = 1000;   // until they've shown they relay too, a hello through the host this often

	struct Contact
	{
		bool speaks = false;       // they relay too: a hello, a probe or a relayed packet came from them
		bool relaying = false;
		uint32_t lastDirect = 0;   // their last packet or probe that came straight from where the game expects them
		uint32_t verdictAt = 0;    // their last probe
		bool hearsUs = false;      // what it said: whether they hear us directly
		uint32_t lastProbe = 0, lastHello = 0;
	};

	inline bool Recent(uint32_t at, uint32_t now) { return at && now - at < Unheard; }
	inline bool HearsThem(const Contact& c, uint32_t now) { return Recent(c.lastDirect, now); }

	// When they first show they relay: through the host unless we already hear them directly.
	// Returns whether this was the first time.
	inline bool Speaks(Contact& c, uint32_t now)
	{
		if (c.speaks)
			return false;
		c.speaks = true;
		c.relaying = !HearsThem(c, now);
		return true;
	}

	// Through the host until direct is shown to work both ways (we hear them and their probe says
	// they hear us); back through the host when they go quiet or say they don't hear us. Never with
	// someone who doesn't relay: their game would drop what the host passes on.
	inline bool ShouldRelay(const Contact& c, uint32_t now, bool always)
	{
		if (!c.speaks)
			return false;
		if (always)
			return true;
		const bool verdict = Recent(c.verdictAt, now);
		if (c.relaying)
			return !(HearsThem(c, now) && verdict && c.hearsUs);
		return !HearsThem(c, now) || (verdict && !c.hearsUs);
	}
}
