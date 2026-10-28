"""A slimmer, straight "stretch" fit for the men's tight jeans mesh (cmBot_mJeansMF02_M): see
tools/sr2/legfit.py.

    python fit.py [game folder]     # writes the mesh into out/STILWATER - HOQ Jeans/
"""
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import legfit  # noqa: E402
import vpp  # noqa: E402

MESH = "cmbot_mjeansmf02_m"
MOD_NAME = "STILWATER - HOQ Jeans"
OUT = HERE / "out" / MOD_NAME


def main(game):
    original = HERE / "original"
    jeans, new = legfit.fit(vpp.Packfile(game / "meshes.vpp_pc"), original, MESH)
    data = bytearray((original / f"{MESH}.g_cmesh_pc").read_bytes())
    for i, p in enumerate(new):
        struct.pack_into("<3f", data, i * jeans["stride"], *p)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{MESH}.cmesh_pc").write_bytes((original / f"{MESH}.cmesh_pc").read_bytes())
    (OUT / f"{MESH}.g_cmesh_pc").write_bytes(bytes(data))
    moved = np.linalg.norm(new - jeans["positions"], axis=1)
    print(f"wrote {OUT / MESH}.g_cmesh_pc: {int((moved > 1e-4).sum())} of {len(new)} vertices moved, "
          f"up to {100 * moved.max():.1f} cm")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
