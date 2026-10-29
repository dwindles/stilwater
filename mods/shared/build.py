"""Tables shared by the Stilwater clothing and weapon mods, built into one loose folder (STILWATER - Shared),
because the loose-file loader only uses the first copy of each file name:

- customization_stores.xtbl: extra stores selling each item,
- customization_items.xtbl: white default colours, the item's and its materials' (the textures
  carry their own colour, and the game multiplies them by the chosen one), which style a store
  shows first, and the new items (CLONES: mods/tees, mods/undercover-jeans), each a copy of an
  existing item with new IDs, its own meshes and one style,
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
sys.path.insert(0, str(HERE.parent / "tees"))
sys.path.insert(0, str(HERE.parent / "gta-shoes"))
sys.path.insert(0, str(HERE.parent / "gta-glasses"))
sys.path.insert(0, str(HERE.parent / "gta-jeans"))
sys.path.insert(0, str(HERE.parent / "gta-tops"))
import glasses  # noqa: E402
import jeans  # noqa: E402
import shoes  # noqa: E402
import strings  # noqa: E402
import tops  # noqa: E402
import tees  # noqa: E402
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
# New items: each a copy of an existing item (item, and the one style it keeps) on its own copies of
# that item's meshes (the mesh file names' prefix, find, becoming replace), taking the place of an
# item nobody wears (takes): its ID, style ID and mesh IDs, its place in the table. Items with IDs
# and mesh IDs of their own, after the table's highest, never load (the stores then crashed on
# them), while the ones in place of existing items have numbers the game already knows. wear: the
# mesh suffixes kept (a tee keeps untucked, male and female, so two mesh IDs are enough).
# name: in the tables and the stores; key: its name's string.
TAKES = {
    "Draco Party Tee": "women's bondage top 1",
    "Supreme Stick Tee": "women's bondage top 2",
    "Plaid Skull Tee": "women's bondage top 3",
    "Supreme Graffiti Tee": "women's chest band",
    "Supreme Smurf Tee": "women's short tube top",
    "Supreme Triple Box Tee": "two-pocket short-sleeve workshirt with tie",
    "Supreme Photo Tee": "Sunshine's shirt",
    "Supreme Numbers Tee": "women's long sleeve blouse",
    # mods/gta-shoes
    "Jordan 4 Fire Red": "women's fuzzy slippers",
    "Jordan 4 Motorsports": "gladiator sandals",
    "Jordan 4 Thunder": "Wong's Shoes",
    "Jordan 4 Lightning": "futuristic biker boots",
    "Jordan 4 Military Blue": "plastic sandals",
    "Jordan 4 White Cement": "men's snakeskin boots",
    "Jordan 4 Raptors": "biker boots 3",
    "Jordan 4 Bred": "biker boots 4",
    "Jordan 5 Black Red": "thong A",
    "Jordan 5 Grape": "women's low-cut thong",
    "Jordan 5 White": "women's low-cut g-string",
    "Jordan 5 Green Bean": "Pasties Variety 1",
    "Jordan 1 '85 Chicago": "cheerleader skirt",
    "Jordan 1 '85 Bred": "women's Cheerleader Top",
    "Jordan 1 '85 Royal": "Pirate Hat",
    # mods/gta-glasses
    "Cartier White Buffs": "old lady glasses",
    "Cartier White Buffs Orange": "Retaliation of the Nerd Glasses",
    "Cartier Brown Wood": "Oval glasses",
    "Cartier Red Wood": "geezer shades",
    "Cartier Iced Out": "protective goggles 1",
    # mods/gta-jeans
    "Traplanta Black Print Jeans": "women's tight low cut latex pants",
    "Traplanta Blue Print Jeans": "women's snakeskin pants",
    "Traplanta Star Jeans": "men's snakeskin pants",
    "Traplanta Wreath Jeans": "women's jean hot pants",
    "Washed Grey Jeans": "women's dress hot pants",
    "Washed Black Jeans": "laced leather biker pants",
    # mods/gta-tops
    "Lead Never Follow Baseball Tee": "women's camisole 3",
    "Red Sleeve Baseball Tee": "women's camisole 4",
    "Cross Baseball Tee": "women's very short camisole",
    "Camo Sleeve Baseball Tee": "women's lycra tank",
    "Nike Tech Black": "women's sweater vest",
    "Nike Tech Grey": "women's denim vest coat 1",
    "Nike Tech Blue": "women's one-piece swimsuit 3",
    "Nike Tech Green": "women's one-piece swimsuit 9",
    "Nike Tech Grey Red": "Judge Robe",
    # mods/glockio
    "GLOCKIO Extended": "tribal extra belt 1",
    "GLOCKIO Drum": "knee Pads for Swat only",
}
CLONES = [dict(name=tee["name"], key="CUST_ITEM_" + tee["base"].upper(), item=tees.SOURCE_ITEM,
               variant=tees.SOURCE_VARIANT, find=tees.SOURCE, replace=tee["base"], wear=("U", "UF"),
               takes=TAKES[tee["name"]]) for tee in tees.TEES] + [
    dict(name="Undercover Jeans", key="CUST_ITEM_CMBOT_MJEANSUC02", item="leather biker pants",
         variant="leather", find="cmBot_uBiker01", replace="cmbot_ubikuc01", wear=("M",),
         takes="assless chaps"),   # mods/undercover-jeans
] + [dict(name=shoe["name"], key="CUST_ITEM_" + shoe["base"].upper(), item=shoes.SOURCE_ITEM,
          variant=shoes.SOURCE_VARIANT, find=shoes.SOURCE, replace=shoe["base"], wear=("USPORSHO01",),
          takes=TAKES[shoe["name"]]) for shoe in shoes.SHOES] + [
    dict(name=item["name"], key="CUST_ITEM_" + item["base"].upper(), item=glasses.SOURCE_ITEM,
         variant=glasses.SOURCE_VARIANT, find=glasses.SOURCE, replace=item["base"], wear=("USHOGO",),
         takes=TAKES[item["name"]]) for item in glasses.GLASSES] + [
    dict(name=item["name"], key="CUST_ITEM_" + item["base"].upper(), item=jeans.SOURCE_ITEM,
         variant=jeans.SOURCE_VARIANT, find=jeans.SOURCE, replace=item["base"], wear=("M", "L"),
         takes=TAKES[item["name"]]) for item in jeans.JEANS] + [
    dict(name=top["name"], key="CUST_ITEM_" + top["base"].upper(), item=tops.GROUPS[top["group"]]["item"],
         variant=tops.GROUPS[top["group"]]["variant"], find=tops.GROUPS[top["group"]]["source"], replace=top["base"],
         wear=tuple(s.upper() for s in tops.GROUPS[top["group"]]["meshes"]), takes=TAKES[top["name"]])
    for top in tops.TOPS] + [
    dict(name=name, key="CUST_ITEM_" + base.upper(), item="police utility belt", variant="belt",
         find="cmX03_uCopUtil01", replace=base, wear=("UCOPUTIL01",), takes=TAKES[name])   # mods/glockio
    for name, base in (("GLOCKIO Extended", "cmx03_uglockx001"), ("GLOCKIO Drum", "cmx03_uglockd001"))]

# Every clothing store sells every item worn in these slots (not tattoos, hair, make-up or
# piercings, which have their own shops).
CLOTHING_SLOTS = {
    "headwear", "eyewear", "undershirt", "overshirt", "coat", "suit", "bottoms", "underwear", "bra",
    "socks", "shoes", "belt", "loose belt", "back pants pocket", "pants chain", "left wrist",
    "right wrist", "short chain", "mid-length chain", "long chain", "short medallion",
    "mid-length medallion", "long medallion", "left index finger", "right index finger",
    "left ring finger", "right ring finger",
}
JEWELLERY = {"left wrist", "right wrist", "short chain", "mid-length chain", "long chain", "short medallion",
             "mid-length medallion", "long medallion", "left index finger", "right index finger",
             "left ring finger", "right ring finger"}
NOT_CLOTHING_STORES = {"Rusty's_Needle", "Shear_Intensity", "Do it Up", "Multiplayer Purchase Clothing"}
STORE_ITEM_LIMIT = 511   # Stilwater core's (DLCSupport.cpp), less one
NEW_ITEMS = [clone["name"] for clone in CLONES]

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


def stores_table(game, items):
    """The stores, every clothing store selling every clothing item of the finished items table
    (CLOTHING_SLOTS) as well as what it sold, minus the items the new ones took the place of."""
    text = vpp.Packfile(game / "common.vpp_pc").read("customization_stores.xtbl").decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    data, rest = data_section(text)
    slots = {re.search(r"<Name>(.*?)</Name>", b).group(1): re.search(r"<Slot>(.*?)</Slot>", b).group(1)
             for b in re.findall(r"<Customization_Item>.*?</Customization_Item>", items, re.S)}
    # Jewellery last: a store that would go over the limit leaves out the jewellery that doesn't fit.
    clothing = sorted((name for name, slot in slots.items() if slot in CLOTHING_SLOTS), key=lambda n: slots[n] in JEWELLERY)
    gone = {clone["takes"] for clone in CLONES}

    def add(match):
        block = match.group(0)
        if re.search(r"<Name>(.*?)</Name>", block).group(1) in NOT_CLOTHING_STORES:
            return block
        block = re.sub(r"[ \t]*<Store_Item>\s*<Item>(.*?)</Item>.*?</Store_Item>\s*",
                       lambda m: "" if m.group(1) in gone else m.group(0), block, flags=re.S)
        at = block.index(newline, block.index("<Items>")) + len(newline)
        missing = [item for item in clothing if f"<Item>{item}</Item>" not in block]
        missing = missing[:STORE_ITEM_LIMIT - block.count("<Store_Item>")]
        block = block[:at] + "".join(newline.join([
            "\t\t\t<Store_Item>", f"\t\t\t\t<Item>{item}</Item>",
            "\t\t\t\t<Variants></Variants>", "\t\t\t\t</Store_Item>"]) + newline for item in missing) + block[at:]
        assert block.count("<Store_Item>") <= STORE_ITEM_LIMIT, re.search(r"<Name>(.*?)</Name>", block).group(1)
        return block

    data = re.sub(r"<Store>.*?</Store>", add, data, flags=re.S)
    for item in [spec["item"] for spec in ITEMS] + NEW_ITEMS:
        assert f"<Item>{item}</Item>" in data, item
    return (data + rest).encode("utf-8")


def clone_items(data):
    """{name of the item taken over: the new item's Customization_Item block} (CLONES)."""
    blocks = {re.search(r"<Name>(.*?)</Name>", b).group(1): b
              for b in re.findall(r"<Customization_Item>.*?</Customization_Item>", data, re.S)}
    # The mesh IDs of every item taken over, shared out: a tee needs two, a taken item may have one.
    spare = [int(m) for clone in CLONES for m in re.findall(r"<MeshID>(\d+)</MeshID>", blocks[clone["takes"]])]
    out = {}
    for clone in CLONES:
        source, taken = blocks[clone["item"]], blocks[clone["takes"]]
        options = re.findall(r"\s*<Wear_Option>.*?</Wear_Option>", source, re.S)
        kept = [o for o in options
                if re.search(r"_([^_<]+)\.cmeshx</Filename>", o).group(1).upper() in clone["wear"]]
        assert len(kept) == len(clone["wear"]), clone["name"]
        start, end = source.index(options[0]), source.index(options[-1]) + len(options[-1])
        block = source[:start] + "".join(kept) + source[end:]
        start, end = block.index("<Variants>") + len("<Variants>"), block.index("</Variants>")
        variant = [v for v in re.findall(r"\s*<Variant>.*?</Variant>", block[start:end], re.S)
                   if f"<Variant_Name>{clone['variant']}</Variant_Name>" in v]
        assert len(variant) == 1, clone["name"]
        block = block[:start] + variant[0] + "\n\t\t\t" + block[end:]
        block = block.replace(f"<Name>{clone['item']}</Name>", f"<Name>{clone['name']}</Name>", 1)
        block = re.sub(r"<DisplayName>.*?</DisplayName>", f"<DisplayName>{clone['key']}</DisplayName>", block, count=1)
        block = re.sub(r"(</Variants>\s*(?:<_Editor>.*?</_Editor>\s*)?<ID>)\d+(</ID>)",
                       lambda m: m.group(1) + re.findall(r"<ID>(\d+)</ID>", taken)[-1] + m.group(2), block, flags=re.S)
        variant_id = re.search(r"<VariantID>(\d+)</VariantID>", taken).group(1)
        block = re.sub(r"<VariantID>\d+</VariantID>", f"<VariantID>{variant_id}</VariantID>", block)
        block = re.sub(r"<MeshID>\d+</MeshID>", lambda m: f"<MeshID>{spare.pop(0)}</MeshID>", block)
        block, n = re.subn(rf"<Filename>{re.escape(clone['find'])}", f"<Filename>{clone['replace']}", block, flags=re.I)
        assert n == block.count("<Filename>"), (clone["name"], n)
        block = re.sub(r"<Clothing_Color>.*?</Clothing_Color>", "<Clothing_Color>White</Clothing_Color>", block)
        block = re.sub(r"<Color>.*?</Color>", "<Color>White</Color>", block)
        out[clone["takes"]] = block
    return out


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

    new = clone_items(data)
    data = re.sub(r"<Customization_Item>.*?</Customization_Item>", edit, data, flags=re.S)
    assert done == set(wanted), set(wanted) - done
    taken = set()

    def take(match):
        name = re.search(r"<Name>(.*?)</Name>", match.group(0)).group(1)
        if name not in new:
            return match.group(0)
        taken.add(name)
        return new[name]

    data = re.sub(r"<Customization_Item>.*?</Customization_Item>", take, data, flags=re.S)
    assert taken == set(new), set(new) - taken
    return compact(data + rest)


def compact(text):
    """The table made smaller. The game reads it into a fixed-size mempool, which the vanilla table
    nearly fills; when the file doesn't fit, no items load at all and the stores crash the game
    (at 0x007BD6F1). Dropped: the items flagged "not ready", which the game skips anyway (after
    the new items took their IDs from the whole table), the editor's notes, and the indentation."""
    def ready(match):
        flags = re.search(r"<Flags>(.*?)</Flags>\s*<Base_Respect", match.group(0), re.S)
        return "" if flags and "not ready" in flags.group(1) else match.group(0)

    text = re.sub(r"[ \t]*<Customization_Item>.*?</Customization_Item>\s*", ready, text, flags=re.S)
    text = re.sub(r"[ \t]*<_Editor>.*?</_Editor>\s*", "", text, flags=re.S)
    return re.sub(r"\n[ \t]+", "\n", text)


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
    for clone in CLONES:
        renames[strings.key_hash(clone["key"])] = clone["name"]
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
    items = items_table(game)
    (out / "customization_items.xtbl").write_bytes(items.encode("utf-8"))
    (out / "customization_stores.xtbl").write_bytes(stores_table(game, items))
    (out / "stilwater_US.le_strings").write_bytes(strings_table(game))
    (out / "weapons.xtbl").write_bytes(weapons_table(game))
    (out / "ammo.xtbl").write_bytes(ammo_table(game))
    print(f"built {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
