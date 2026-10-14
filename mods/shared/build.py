"""Tables shared by the Stilwater clothing mods, built into one loose folder (STILWATER - Shared),
because the loose-file loader only uses the first copy of each file name:

- customization_stores.xtbl: extra stores selling each item,
- customization_items.xtbl: white default colours (the textures carry their own colour, and the
  game multiplies them by the chosen one) and which style a store shows first,
- stilwater_US.le_strings: the items' new English names. Stilwater core loads this table ahead of
  the game's, so an entry with an existing key's hash renames that string. Keys are found by the
  vanilla text, which must be unique.

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
    dict(item="men's tight jeans", vanilla_name="Men's Jeans 1", name="HOQ Skinny Jeans"),
    dict(item="tye-dye T-shirt", vanilla_name="Tie Dye Tee", name="HOQ Queen Bee Tee",
         first_variant="cmUnS_uTShirt04_U"),  # the plain style, not the tie-dye pattern
]


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
    table = strings.read(vpp.Packfile(game / "patch.vpp_pc").read("static_US.le_strings"))
    renames = {}
    for spec in ITEMS:
        keys = [key for key, text in table if text == spec["vanilla_name"]]
        assert len(keys) == 1, (spec["vanilla_name"], keys)
        renames[keys[0]] = spec["name"]
    return strings.write(renames)


def main(game):
    out = HERE / "out" / MOD_NAME
    out.mkdir(parents=True, exist_ok=True)
    (out / "customization_stores.xtbl").write_bytes(stores_table(game))
    (out / "customization_items.xtbl").write_bytes(items_table(game))
    (out / "stilwater_US.le_strings").write_bytes(strings_table(game))
    print(f"built {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
