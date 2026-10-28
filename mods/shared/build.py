"""Tables shared by the Stilwater clothing and weapon mods, built into one loose folder (STILWATER - Shared),
because the loose-file loader only uses the first copy of each file name:

- customization_stores.xtbl: extra stores selling each item,
- customization_items.xtbl: white default colours, the item's and its materials' (the textures
  carry their own colour, and the game multiplies them by the chosen one) and which style a store
  shows first,
- weapons.xtbl and ammo.xtbl: the weapon mods' stats, sounds and ammo (WEAPONS, AMMO),
- stilwater_US.le_strings: the items' new English names, and other strings the mods rename
  (STRINGS). Stilwater core loads this table ahead of the game's, so an entry with an existing
  key's hash renames that string; an item's key is its DisplayName in customization_items.

    python build.py [game folder]     # writes out/STILWATER - Shared/
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import strings  # noqa: E402
import vpp  # noqa: E402

MOD_NAME = "STILWATER - Shared"
CLOTHING_STORES = ["Sloppy_Seconds", "Branded", "Impressions", "On_the_Rag"]

ITEMS = [
    dict(item="men's tight jeans", name="HOQ Skinny Jeans"),
    dict(item="tye-dye T-shirt", name="HOQ Queen Bee Tee",
         first_variant="cmUnS_uTShirt04_U"),  # the plain style, not the tie-dye pattern
    dict(item="canvas shoes", name="HOQ Arena Highs"),
    dict(item="sports shoes with strap", name="HOQ Uptempo"),
    dict(item="men's tight torn jeans", name="HOQ Stretch Jeans"),
    dict(item="hoody", name="HOQ Balenciaga Hoodie"),
    dict(item="hoody with hat", name="HOQ Atom Hoodie"),
    dict(item="track jacket", name="HOQ Tech Fleece"),
    dict(item="men's leather biker jacket", name="HOQ Black Jacket"),
    dict(item="basic backpack", name="HOQ Realtree Backpack"),
]

# Other strings renamed: key, or its hash where the key isn't known, to the new text.
STRINGS = {
    "GLOCK": "Glock 19 Switch",               # the NR4 (mods/glock-switch)
    0xa533a06a: "Give Glock 19 Switch",       # its debug menu entry, "Give NR4"
    "TEC9": "Micro Draco",                    # the T3K Urban (mods/draco)
    0xe703b989: "Platinum Micro Draco",       # "Platinum T3K Urban"
    0xa634b4ed: "Give Micro Draco",           # "Give T3K"
}

# Weapon changes (weapons.xtbl): weapon name to {tag: value}. A release sound the weapon lacks goes
# after its Secondary_Fire_Sound, where the automatics have theirs.
WEAPONS = {
    # Glock 19 with a switch: full auto at about 1200 rounds a minute, a 50-round drum, SMG pickups.
    # SR2's automatics play their fire sound as a loop while the trigger is held and a release sound
    # after it, so the pistol's single-shot sound (heard on only some shots) becomes the MAC-10's.
    "glock": dict(Trigger_Type="burst", Magazine_Size=50, Refire_Delay=50, min_ammo_given=20, max_ammo_given=40,
                  Fire_Sound="MAC10_FIRE_PLAYER", NPC_Fire_Sound="MAC10_FIRE_NPC",
                  Fire_Release_Sound="MAC10_RELEASE_PLAYER", NPC_Fire_Release_Sound="MAC10_RELEASE_NPC"),
    # The MAC-10's own cues now play the Glock's sounds (mods/glock-switch), so it takes the T3K's.
    "mac10": dict(Fire_Sound="TEC9_FIRE_PLAYER", NPC_Fire_Sound="TEC9_FIRE_NPC",
                  Fire_Release_Sound="TEC9_RELEASE_PLAYER", NPC_Fire_Release_Sound="TEC9_RELEASE_NPC"),
    # Micro Draco, an AK pistol: the K6 Krukov's (AK-47) sounds.
    "tec9": dict(Fire_Sound="AK47_FIRE_PLAYER", NPC_Fire_Sound="AK47_FIRE_NPC",
                 Fire_Release_Sound="AK47_RELEASE_PLAYER", NPC_Fire_Release_Sound="AK47_RELEASE_NPC"),
}
RELEASE_SOUNDS = ("Fire_Release_Sound", "NPC_Fire_Release_Sound")

# Ammo changes (ammo.xtbl): ammo name to {tag: value}, every copy of the tag (clip_size is also the
# store's pack size). Every pistol shares "Bullet Pistol" and every SMG (the Draco too) "Bullet SMG";
# 20000 carried is what the user asked for (vanilla 250 and 1000).
AMMO = {"Bullet Pistol": dict(Max_in_Reserve=20000, clip_size=50),
        "Bullet SMG": dict(Max_in_Reserve=20000)}


def data_section(text):
    """(data, rest): edits go before <TableDescription>, which describes the table for the editor."""
    split = text.find("<TableDescription>")
    split = len(text) if split < 0 else split
    return text[:split], text[split:]


def stores_table(game):
    text = vpp.Packfile(game / "common.vpp_pc").read("customization_stores.xtbl").decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    data, rest = data_section(text)

    def add(match):
        block = match.group(0)
        if re.search(r"<Name>(.*?)</Name>", block).group(1) not in CLOTHING_STORES:
            return block
        at = block.index(newline, block.index("<Items>")) + len(newline)
        for spec in ITEMS:
            if f"<Item>{spec['item']}</Item>" not in block:
                block = block[:at] + newline.join([
                    "\t\t\t<Store_Item>", f"\t\t\t\t<Item>{spec['item']}</Item>",
                    "\t\t\t\t<Variants></Variants>", "\t\t\t\t</Store_Item>"]) + newline + block[at:]
        return block

    data = re.sub(r"<Store>.*?</Store>", add, data, flags=re.S)
    for spec in ITEMS:
        assert data.count(f"<Item>{spec['item']}</Item>") >= len(CLOTHING_STORES), spec["item"]
    return (data + rest).encode("utf-8")


def items_table(game):
    # patch.vpp_pc carries the newer copy of this table.
    text = vpp.Packfile(game / "patch.vpp_pc").read("customization_items.xtbl").decode("utf-8")
    data, rest = data_section(text)
    wanted = {spec["item"]: spec for spec in ITEMS}
    done = set()

    def edit(match):
        block = match.group(0)
        name = re.search(r"<Name>(.*?)</Name>", block).group(1)
        spec = wanted.get(name)
        if spec is None:
            return block
        block = re.sub(r"<Clothing_Color>.*?</Clothing_Color>", "<Clothing_Color>White</Clothing_Color>", block)
        # Some items also give their materials default colours.
        block = re.sub(r"<Color>.*?</Color>", "<Color>White</Color>", block)
        if "first_variant" in spec:
            start, end = block.index("<Variants>") + len("<Variants>"), block.index("</Variants>")
            variants = re.findall(r"\s*<Variant>.*?</Variant>", block[start:end], re.S)
            first = [v for v in variants if f"<Variant_Name>{spec['first_variant']}</Variant_Name>" in v]
            assert len(first) == 1, name
            total = sum(map(len, variants))
            assert block[start:start + total] == "".join(variants), name
            ordered = first + [v for v in variants if v is not first[0]]
            block = block[:start] + "".join(ordered) + block[start + total:]
        done.add(name)
        return block

    data = re.sub(r"<Customization_Item>.*?</Customization_Item>", edit, data, flags=re.S)
    assert done == set(wanted), set(wanted) - done
    return (data + rest).encode("utf-8")


def strings_table(game):
    text = vpp.Packfile(game / "patch.vpp_pc").read("customization_items.xtbl").decode("utf-8")
    table = dict(strings.read(vpp.Packfile(game / "patch.vpp_pc").read("static_US.le_strings")))
    display = {re.search(r"<Name>(.*?)</Name>", m.group(0)).group(1): re.search(r"<DisplayName>(.*?)</DisplayName>", m.group(0)).group(1)
               for m in re.finditer(r"<Customization_Item>.*?</Customization_Item>", text, re.S)}
    renames = {}
    for spec in ITEMS:
        key = strings.key_hash(display[spec["item"]])
        assert key in table, (spec["item"], display[spec["item"]])
        renames[key] = spec["name"]
    for key, text in STRINGS.items():
        key = strings.key_hash(key) if isinstance(key, str) else key
        assert key in table, hex(key)
        renames[key] = text
    return strings.write(renames)


def weapons_table(game):
    # m_pat.vpp_pc carries the newer copy of these tables.
    text = vpp.Packfile(game / "m_pat.vpp_pc").read("weapons.xtbl").decode("utf-8")
    done = set()

    def edit(match):
        block = match.group(0)
        name = re.search(r"<Name>(.*?)</Name>", block)
        spec = WEAPONS.get(name.group(1)) if name else None
        if spec is None:
            return block
        missing = []
        for tag, value in spec.items():
            block, n = re.subn(rf"<{tag}>.*?</{tag}>", f"<{tag}>{value}</{tag}>", block, count=1)
            if n == 0:
                assert tag in RELEASE_SOUNDS, (name.group(1), tag)
                missing.append((tag, value))
        if missing:
            block, n = re.subn(r"(([ \t]*)<Secondary_Fire_Sound>.*?</Secondary_Fire_Sound>(\r?\n))",
                               lambda m: m.group(1) + "".join(f"{m.group(2)}<{tag}>{value}</{tag}>{m.group(3)}"
                                                              for tag, value in missing), block, count=1)
            assert n == 1, name.group(1)
        done.add(name.group(1))
        return block

    edited = re.sub(r"<Weapon>.*?</Weapon>", edit, text, flags=re.S)
    assert done == set(WEAPONS), set(WEAPONS) - done
    return edited.encode("utf-8")


def ammo_table(game):
    text = vpp.Packfile(game / "m_pat.vpp_pc").read("ammo.xtbl").decode("utf-8")
    done = set()

    def edit(match):
        block = match.group(0)
        name = re.search(r"<Name>(.*?)</Name>", block).group(1)
        if name not in AMMO:
            return block
        for tag, value in AMMO[name].items():
            block, n = re.subn(rf"<{tag}>.*?</{tag}>", f"<{tag}>{value}</{tag}>", block)
            assert n, (name, tag)
        done.add(name)
        return block

    edited = re.sub(r"<Ammo>\s*<Name>.*?</Ammo>", edit, text, flags=re.S)
    assert done == set(AMMO), set(AMMO) - done
    return edited.encode("utf-8")


def main(game):
    out = HERE / "out" / MOD_NAME
    out.mkdir(parents=True, exist_ok=True)
    (out / "customization_stores.xtbl").write_bytes(stores_table(game))
    (out / "customization_items.xtbl").write_bytes(items_table(game))
    (out / "stilwater_US.le_strings").write_bytes(strings_table(game))
    (out / "weapons.xtbl").write_bytes(weapons_table(game))
    (out / "ammo.xtbl").write_bytes(ammo_table(game))
    print(f"built {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
