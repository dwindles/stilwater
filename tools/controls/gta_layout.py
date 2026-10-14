"""Apply GTA Online-style controls to Saints Row 2's input.bin, for controller and keyboard/mouse.

input.bin (%LOCALAPPDATA%\\THQ\\Saints Row 2\\input.bin) is an array of
(int32 keyboard key, int32 pad button) pairs indexed by the game's PC_BTN_* action
ids. Keyboard keys are DirectInput scan codes; 256 and 257 are the left and right mouse
buttons. The first time it runs, the original file is copied to input.bin.bak (the launcher's
"Previous layout" restores it). The game must be closed when this runs, since it keeps its
bindings in memory and rewrites the file when you accept changes in Options.

usage: python gta_layout.py [path\\to\\input.bin]
"""

import os
import shutil
import struct
import sys

# Pad button codes used by the game.
A, B, X, Y = 0, 1, 2, 3
LB, RB, BACK, START, L3, R3, LT, RT = 4, 5, 6, 7, 8, 9, 10, 11
DPAD_RIGHT, DPAD_UP, DPAD_LEFT, DPAD_DOWN = 16, 17, 18, 19

# Keyboard: DirectInput scan codes, plus the mouse buttons.
KEY_Q, KEY_E, KEY_R, KEY_F, KEY_G = 0x10, 0x12, 0x13, 0x21, 0x22
KEY_X, KEY_C, KEY_M = 0x2D, 0x2E, 0x32
KEY_TAB, KEY_LCTRL = 0x0F, 0x1D
KEY_COMMA, KEY_PERIOD = 0x33, 0x34
KEY_NUMPAD8, KEY_NUMPAD5 = 0x48, 0x4C
MOUSE_LEFT, MOUSE_RIGHT = 256, 257

# PC_BTN_* action id -> pad button. Actions not listed keep their current binding.
GTA_ONLINE_PAD = {
    # On foot
    35: RT,          # ATTACK              shoot
    16: LT,          # FINE_AIM            aim
    36: RB,          # ATTACK2             melee (GTA's cover button; SR2 has no cover)
    18: A,           # SPRINT
    5: X,            # JUMP
    14: B,           # RELOAD
    4: Y,            # ACTION              enter vehicle / use
    6: LB,           # RADIAL              weapon wheel
    15: L3,          # CROUCH              stealth
    17: R3,          # GRAB_HUMAN          human shield
    # Vehicles
    37: RT,          # ACCELERATE
    38: LT,          # REVERSE             brake / reverse
    7: RB,           # BREAK               handbrake
    26: L3,          # HORN
    49: R3,          # VEHICLE_LOOK_BEHIND
    57: A,           # NITRO               boost
    56: X,           # HYDRAULICS
    29: DPAD_LEFT,   # RADIO_PREV
    30: DPAD_RIGHT,  # RADIO_NEXT
    # Aircraft
    50: RT,          # AIR_ACCELERATE
    51: LT,          # AIR_DECELERATE
    47: LB,          # HELI_TURN_LEFT      rudder left
    48: RB,          # HELI_TURN_RIGHT     rudder right
}

# PC_BTN_* action id -> keyboard key or mouse button, following GTA V's PC defaults. Movement
# (WASD), sprint (Shift), jump and handbrake (Space), reload (R) and weapon slots (1-8)
# already match and are left alone, as are aircraft, menu and chat keys.
GTA_ONLINE_KEYBOARD = {
    # On foot
    35: MOUSE_LEFT,  # ATTACK              shoot
    16: MOUSE_RIGHT, # FINE_AIM            aim (was V)
    36: KEY_Q,       # ATTACK2             melee (was right mouse)
    4: KEY_F,        # ACTION              enter vehicle / use (was E)
    6: KEY_TAB,      # RADIAL              weapon wheel (was Q)
    15: KEY_LCTRL,   # CROUCH              stealth (was C)
    17: KEY_G,       # GRAB_HUMAN          human shield (was Ctrl)
    20: KEY_M,       # MAP                 (was Tab)
    # Vehicles
    26: KEY_E,       # HORN                (was H)
    49: KEY_C,       # VEHICLE_LOOK_BEHIND (was X)
    27: KEY_X,       # CRUISE              (was C)
    29: KEY_COMMA,   # RADIO_PREV          (was Left)
    30: KEY_PERIOD,  # RADIO_NEXT          (was Right)
    64: KEY_NUMPAD8, # MOTO_PITCH_UP       lean forward (was F)
    65: KEY_NUMPAD5, # MOTO_PITCH_DOWN     lean back (was R)
}

KEYBOARD, PAD = 0, 1


def default_path():
    return os.path.join(os.environ["LOCALAPPDATA"], "THQ", "Saints Row 2", "input.bin")


def apply(path, layouts):
    """layouts: [(column, {action: code})]"""
    data = bytearray(open(path, "rb").read())
    if len(data) % 8:
        raise ValueError(f"{path} is not a list of 8-byte bindings")
    count = len(data) // 8
    if not os.path.exists(path + ".bak"):
        shutil.copy2(path, path + ".bak")
    changed = 0
    for column, layout in layouts:
        for action, code in layout.items():
            if action >= count:
                raise ValueError(f"action {action} is out of range for this input.bin ({count} entries)")
            struct.pack_into("<i", data, action * 8 + column * 4, code)
            changed += 1
    with open(path, "wb") as f:
        f.write(data)
    return changed


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else default_path()
    changed = apply(target, [(PAD, GTA_ONLINE_PAD), (KEYBOARD, GTA_ONLINE_KEYBOARD)])
    print(f"Applied GTA Online controls ({changed} bindings) to {target} (original kept in {target}.bak)")
