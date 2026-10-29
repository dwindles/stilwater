"""The Stilwater tees (build.py bakes them; mods/shared adds them to the game's tables).

base: the clone's file name, as long as SOURCE. name: its name in the stores. fabric: the shirt's
colour (0-255). front/back: a photo in ref/ with, in its pixels, the print's box, a patch of plain
fabric, the shirt's centre line, the neckline at the centre and the hem (or, when the photo cuts it off, the body's width under the arms);
optional: scale stretches the print, rotate turns a shirt photographed at an angle, threshold is how
far from the fabric colour a pixel must be to count as print.
"""
SOURCE = "cmuns_utshirt04"   # SR2's "tye-dye T-shirt"
SOURCE_ITEM = "tye-dye T-shirt"
SOURCE_VARIANT = "cmUnS_uTShirt04_U"   # its plain style
SUFFIXES = ("u", "uf", "h", "hf", "m", "mf", "l", "lf")   # its meshes: untucked, tucked high/mid/low; f female

TEES = [
    dict(base="cmuns_utsw00001", name="Draco Party Tee", fabric=(28, 28, 31),
         front=dict(photo="draco-party-front.jpg", box=(395, 390, 880, 722), fabric=(300, 800, 500, 950),
                    centre=640, neck=258, hem=1050),
         back=dict(photo="draco-party-back.jpg", box=(420, 375, 880, 730), fabric=(400, 800, 900, 1000),
                   centre=665, neck=240, hem=1112)),
    dict(base="cmuns_utsw00002", name="Supreme Stick Tee",
         front=dict(photo="stick-box-front.jpg", box=(490, 395, 725, 555), fabric=(420, 650, 820, 880),
                    centre=620, neck=258, hem=950)),
    dict(base="cmuns_utsw00003", name="Plaid Skull Tee",
         front=dict(photo="plaid-skull-front.jpg", box=(350, 285, 900, 765), fabric=(300, 850, 1000, 1150),
                    centre=630, neck=150, width=(165, 1125))),
    dict(base="cmuns_utsw00004", name="Supreme Graffiti Tee", fabric=(30, 29, 31),
         front=dict(photo="graffiti-front.jpg", box=(415, 530, 845, 840), fabric=(150, 900, 500, 1150),
                    centre=660, neck=335, width=(0, 1240), scale=1.3, threshold=0.3)),
    dict(base="cmuns_utsw00005", name="Supreme Smurf Tee",
         front=dict(photo="smurf-front.jpg", box=(300, 290, 1015, 1080), fabric=(480, 500, 600, 560),
                    centre=640, neck=282, hem=1150),
         back=dict(photo="smurf-back.jpg", box=(270, 280, 990, 495), fabric=(450, 600, 800, 900),
                   centre=640, neck=192, hem=1035)),
    dict(base="cmuns_utsw00006", name="Supreme Triple Box Tee",
         front=dict(photo="triple-box-front.jpg", box=(535, 435, 720, 615), fabric=(300, 700, 500, 900),
                    centre=640, neck=298, hem=1095),
         back=dict(photo="triple-box-back.jpg", box=(310, 225, 955, 920), fabric=(650, 950, 900, 1080),
                   centre=630, neck=160, hem=1135)),
    dict(base="cmuns_utsw00007", name="Supreme Photo Tee",
         front=dict(photo="photo-front.jpg", box=(420, 305, 920, 580), fabric=(400, 700, 850, 900),
                    centre=640, neck=195, hem=1240)),
    dict(base="cmuns_utsw00008", name="Supreme Numbers Tee",
         front=dict(photo="numbers-front.jpg", box=(470, 430, 955, 755), fabric=(350, 850, 750, 1050),
                    centre=835, neck=330, width=(150, 1120), rotate=17)),
]
