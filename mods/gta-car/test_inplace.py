"""In-place edit test: the Voxel (car_4dr_sports01) with its main shell 40% taller and its outer
shell collapsed, same file size, to check that edited car geometry loads as a loose file."""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import vpp  # noqa: E402

GAME = Path(r"E:\SteamLibrary\steamapps\common\Saints Row 2")
CAR = "car_4dr_sports01"
STRIDE = 36
SHELL = (0, 3365)        # vertex buffer offset, count of part 0 (main shell + interior)
OUTER = (132544, 2488)   # part 1 (outer shell, body kit)

data = bytearray(vpp.Packfile(GAME / "meshes.vpp_pc").read(f"{CAR}.g_car_pc"))
for (offset, count), edit in ((SHELL, "stretch"), (OUTER, "collapse")):
    raw = np.frombuffer(data, dtype=np.uint8, count=STRIDE * count, offset=offset).reshape(count, STRIDE).copy()
    pos = np.frombuffer(raw[:, :12].tobytes(), dtype="<f4").reshape(count, 3).copy()
    if edit == "stretch":
        pos[:, 1] = pos[:, 1] * 1.4
    else:
        pos[:] = 0
    raw[:, :12] = np.frombuffer(pos.astype("<f4").tobytes(), dtype=np.uint8).reshape(count, 12)
    data[offset:offset + STRIDE * count] = raw.tobytes()

out = HERE / "out" / "STILWATER - Car Test"
out.mkdir(parents=True, exist_ok=True)
(out / f"{CAR}.g_car_pc").write_bytes(data)
print("wrote", out / f"{CAR}.g_car_pc", len(data))
