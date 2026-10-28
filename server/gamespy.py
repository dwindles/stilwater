"""Pieces of the GameSpy protocols that several services share: the \\key\\value message format,
the server list cipher, the password encoding used for new accounts and the login hashes."""
import base64
import hashlib
import secrets
import string

GAME_NAME = "srow2pc"
# The game's secret key, built on the stack before both ServerBrowserNew calls (0x008D0180, 0x00811C30).
SECRET_KEY = b"odvimE"
PRODUCT_ID = 11405
NAMESPACE_ID = 1
# Public half of Stilwater Online's AuthService key (/etc/stilwater-online/authservice.pem on the
# server). The core writes it over GameSpy's key in the exe; a different server needs its own.
AUTH_PUBLIC_KEY = ("c961cff1260ab59388cb66710a2a1c502d2e60545ac4adcba7772290cd0077b282851fd20137e9ac5d2b7af96ed8d918"
                   "e2a8dd5d955823621abeeea123fdb78b742003291cfdc77c50d149d715c61d90d74848a6fc468085dbc351bd3e965fdb"
                   "0294e525020406933191d5248640a7ab22561ff9ad8b7ef3a8249ee1fd639a55")


def parse(message: str) -> tuple[str, dict[str, str]]:
    """'\\login\\\\user\\a@b\\final\\' -> ('login', {'login': '', 'user': 'a@b'}). The first key
    is the command; later duplicates of a key are ignored."""
    parts = message.split("\\")
    fields: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        if parts[i] == "final":
            break
        fields.setdefault(parts[i], parts[i + 1])
    command = parts[1] if len(parts) > 1 else ""
    return command, fields


def message(*pairs) -> bytes:
    """message(('lc', 2), ('sesskey', 5)) -> b'\\lc\\2\\sesskey\\5\\final\\'."""
    text = "".join(f"\\{key}\\{clean(value)}" for key, value in pairs)
    return (text + "\\final\\").encode("latin-1", "replace")


def clean(value) -> str:
    return str(value).replace("\\", "")


def md5(text: str) -> str:
    return hashlib.md5(text.encode("latin-1", "replace")).hexdigest()


def challenge(length: int = 10) -> str:
    return "".join(secrets.choice(string.ascii_uppercase) for _ in range(length))


def login_hash(password_md5: str, user: str, first: str, second: str) -> str:
    """The client proves its password with first = its challenge, second = ours; our proof back
    swaps them."""
    return md5(password_md5 + " " * 48 + user + first + second + password_md5)


def _int32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def _lame(num: int) -> int:
    c = (num >> 16) & 0xFFFF
    a = num & 0xFFFF
    c *= 0x41A7
    a *= 0x41A7
    a = _int32(a + ((c & 0x7FFF) << 16))
    if a < 0:
        a = (a & 0x7FFFFFFF) + 1
    a = _int32(a + (c >> 15))
    if a < 0:
        a = (a & 0x7FFFFFFF) + 1
    return a


def decode_password(text: str) -> str:
    """GameSpy's password encoding (passenc/passwordenc): base64 with [ ] _ for + / =, over the
    password XORed with a fixed pseudo-random sequence seeded with "gspy"."""
    data = bytearray(base64.b64decode(text.replace("[", "+").replace("]", "/").replace("_", "=")))
    num = 0x79707367
    for i in range(len(data)):
        num = _lame(num)
        data[i] ^= num % 0xFF
    return data.decode("latin-1")


def encode_password(password: str) -> str:
    data = bytearray(password.encode("latin-1"))
    num = 0x79707367
    for i in range(len(data)):
        num = _lame(num)
        data[i] ^= num % 0xFF
    return base64.b64encode(bytes(data)).decode().replace("+", "[").replace("/", "]").replace("=", "_")


class ListCipher:
    """The server list stream cipher (GameSpy's GOACrypt, Michael Paul Johnson's Sapphire II).
    Its 8-byte key mixes the client's list challenge with ours and the game's secret key, the way
    the game does at 0x008E78B0."""

    def __init__(self, client_challenge: bytes, server_challenge: bytes, secret: bytes = SECRET_KEY):
        key = bytearray(client_challenge[:8])
        for i, byte in enumerate(server_challenge):
            key[(secret[i % len(secret)] * i) & 7] ^= key[i & 7] ^ byte
        cards = list(range(256))
        rsum = keypos = 0
        for i in range(255, -1, -1):
            swap = 0
            if i:
                mask = 1
                while mask < i:
                    mask = (mask << 1) + 1
                tries = 0
                while True:
                    rsum = (cards[rsum] + key[keypos]) & 0xFF
                    keypos += 1
                    if keypos >= len(key):
                        keypos = 0
                        rsum = (rsum + len(key)) & 0xFF
                    swap = rsum & mask
                    tries += 1
                    if tries > 11:
                        swap %= i
                    if swap <= i:
                        break
            cards[i], cards[swap] = cards[swap], cards[i]
        self.cards = cards
        self.rotor, self.ratchet, self.avalanche = cards[1], cards[3], cards[5]
        self.last_plain, self.last_cipher = cards[7], cards[rsum]

    def _step(self, byte: int, encrypting: bool) -> int:
        c = self.cards
        self.ratchet = (self.ratchet + c[self.rotor]) & 0xFF
        self.rotor = (self.rotor + 1) & 0xFF
        swap = c[self.last_cipher]
        c[self.last_cipher] = c[self.ratchet]
        c[self.ratchet] = c[self.last_plain]
        c[self.last_plain] = c[self.rotor]
        c[self.rotor] = swap
        self.avalanche = (self.avalanche + c[swap]) & 0xFF
        out = byte ^ c[(c[self.avalanche] + c[self.rotor]) & 0xFF] ^ \
            c[c[(c[self.last_plain] + c[self.last_cipher] + c[self.ratchet]) & 0xFF]]
        if encrypting:
            self.last_plain, self.last_cipher = byte, out
        else:
            self.last_plain, self.last_cipher = out, byte
        return out

    def encrypt(self, data: bytes) -> bytes:
        return bytes(self._step(b, True) for b in data)

    def decrypt(self, data: bytes) -> bytes:
        return bytes(self._step(b, False) for b in data)
