#pragma once

// Co-op past two players between friends whose routers won't let two joined players reach each
// other: their packets go through the host instead ([Stilwater] CoopRelay).
namespace CoopRelay
{
	void Init();     // at startup, after SecondCopy (these socket hooks go around its own)
	void Update();   // every frame: notes who is in the co-op session
}
