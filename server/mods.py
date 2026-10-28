"""Shared mods: players upload the mods they added to the launcher and get a code; whoever enters the
code gets the same mods. Served at https://holdonquietly.com/stilwater/mods/ (nginx passes the API
to this server and serves the files itself, see server/nginx-holdonquietly-mods.conf):

  POST /stilwater/mods/missing        {"hashes": [sha256, ...]} -> {"missing": [...]}       signed in
  PUT  /stilwater/mods/blob/<sha256>  the file itself                                          signed in
  POST /stilwater/mods/share          {"mods": [{"name", "enabled", "files": [{"path", "sha256", "size"}]}]}
                                      -> {"code": "SW-XXXX-XXXX"}                                signed in
  GET  /stilwater/mods/share/<code>   the shared list (as posted, plus "by")
  GET  /stilwater/mods/file/<sha256>  a file (nginx serves these straight from the folder)

Signed in = an X-Stilwater-Ticket header with the login ticket (\\lt\\) Presence gave the launcher.
Files are stored once by their SHA-256, whoever uploads them. Only the game's own kinds of files are
taken, never programs, so a code can't put anything on a PC that runs outside the game."""
import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import time

import notify

log = logging.getLogger("mods")

PREFIX = "/stilwater/mods/"
MAX_FILE = 200 * 1024 * 1024          # one file
MAX_ACCOUNT = 1024 * 1024 * 1024      # everything one player has uploaded
MAX_MODS = 100                        # mods in one share
MAX_FILES = 5000                      # files in one share
KEEP_DAYS = 120                       # a share nobody has opened in this long is removed
CODE_LETTERS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"   # no 0/O or 1/I

# The game's file kinds: anything ending in _pc (textures, meshes, animations, chunks, cars ...)
# plus its tables, scripts, strings, audio banks, and notes.
ALLOWED = re.compile(r"\.([a-z0-9_]+_pc|xtbl|lua|le_strings|cxt|xwb|xsb|xgs|vint_doc|vint_proj|txt|dat|png|jpg)$")
SEGMENT = re.compile(r"^[A-Za-z0-9 _.,'()&+\-\[\]]{1,120}$")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
HASH = re.compile(r"^[0-9a-f]{64}$")


class ModError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status, self.text = status, text


def safe_name(name: str) -> bool:
    return bool(SEGMENT.match(name)) and name.strip(" .") == name and name.split(".")[0].lower() not in RESERVED


def safe_path(path: str) -> bool:
    """A file's place inside its mod folder: relative, forward slashes, nothing that climbs out."""
    parts = path.split("/")
    return 0 < len(parts) <= 8 and len(path) <= 240 and all(safe_name(p) for p in parts) \
        and bool(ALLOWED.search(path.lower()))


class ModStore:
    def __init__(self, data: str, files: str, nick_of):
        """data: the server's private folder (the list of shares goes there). files: where the files
        go, a folder of its own that nginx can read (/var/lib/stilwater-mods)."""
        self.blobs = files
        os.makedirs(self.blobs, exist_ok=True)
        os.chmod(self.blobs, 0o755)
        self.nick_of = nick_of
        self.db = sqlite3.connect(os.path.join(data, "mods.db"))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS blobs (hash TEXT PRIMARY KEY, size INTEGER, uploader INTEGER, created INTEGER);
            CREATE TABLE IF NOT EXISTS shares (code TEXT PRIMARY KEY, owner INTEGER, digest TEXT, body TEXT,
                                               created INTEGER, used INTEGER);
            CREATE INDEX IF NOT EXISTS shares_owner ON shares (owner, digest);
        """)

    def path(self, digest: str) -> str:
        return os.path.join(self.blobs, digest)

    def has(self, digest: str) -> bool:
        return os.path.exists(self.path(digest))

    # --- API

    def missing(self, body: bytes) -> dict:
        hashes = json.loads(body).get("hashes", [])
        if not isinstance(hashes, list) or len(hashes) > MAX_FILES:
            raise ModError(400, "Too many files.")
        return {"missing": sorted({h for h in hashes if isinstance(h, str) and HASH.match(h) and not self.has(h)})}

    async def receive(self, reader: asyncio.StreamReader, digest: str, length: int, owner: int) -> dict:
        """Streams one uploaded file to disk, checking its size, its hash and the uploader's quota."""
        if not HASH.match(digest):
            raise ModError(400, "That isn't a file hash.")
        if length <= 0 or length > MAX_FILE:
            raise ModError(413, f"Files can be up to {MAX_FILE // (1024 * 1024)} MB.")
        if self.has(digest):
            await self._drain(reader, length)
            return {"ok": True}
        used = self.db.execute("SELECT COALESCE(SUM(size), 0) FROM blobs WHERE uploader = ?", (owner,)).fetchone()[0]
        if used + length > MAX_ACCOUNT:
            raise ModError(413, f"You've used your {MAX_ACCOUNT // (1024 * 1024)} MB of shared mods.")
        temporary = self.path(digest) + f".{secrets.token_hex(4)}.part"
        sha = hashlib.sha256()
        try:
            with open(temporary, "wb") as f:
                left = length
                while left:
                    chunk = await asyncio.wait_for(reader.read(min(left, 1 << 20)), 60)
                    if not chunk:
                        raise ModError(400, "The upload stopped.")
                    sha.update(chunk)
                    f.write(chunk)
                    left -= len(chunk)
            if sha.hexdigest() != digest:
                raise ModError(400, "The file arrived damaged. Try again.")
            os.chmod(temporary, 0o644)
            os.replace(temporary, self.path(digest))
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        self.db.execute("INSERT OR REPLACE INTO blobs VALUES (?, ?, ?, ?)", (digest, length, owner, int(time.time())))
        self.db.commit()
        return {"ok": True}

    @staticmethod
    async def _drain(reader: asyncio.StreamReader, length: int):
        while length:
            chunk = await asyncio.wait_for(reader.read(min(length, 1 << 20)), 60)
            if not chunk:
                return
            length -= len(chunk)

    def share(self, body: bytes, owner: int) -> dict:
        mods = json.loads(body).get("mods")
        if not isinstance(mods, list) or not mods:
            raise ModError(400, "There are no mods to share.")
        if len(mods) > MAX_MODS:
            raise ModError(400, f"Share up to {MAX_MODS} mods at a time.")
        clean, names, count = [], set(), 0
        for mod in mods:
            name = str(mod.get("name", ""))
            if not safe_name(name) or name.upper().startswith(("STILWATER - ", "JUICED - ")) or name.lower() in names:
                raise ModError(400, f"\"{name}\" can't be shared.")
            names.add(name.lower())
            files, paths = [], set()
            for f in mod.get("files", []):
                path, digest, size = str(f.get("path", "")), str(f.get("sha256", "")), f.get("size")
                if not safe_path(path) or path.lower() in paths:
                    raise ModError(400, f"{name}: {path} isn't a game file, so it can't be shared.")
                if not HASH.match(digest) or not isinstance(size, int) or not self.has(digest):
                    raise ModError(400, f"{name}: {path} wasn't uploaded.")
                paths.add(path.lower())
                files.append({"path": path, "sha256": digest, "size": size})
            if not files:
                raise ModError(400, f"{name} has no files.")
            count += len(files)
            clean.append({"name": name, "enabled": bool(mod.get("enabled", True)), "files": files})
        if count > MAX_FILES:
            raise ModError(400, "Too many files.")
        text = json.dumps(clean, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(text.encode()).hexdigest()
        now = int(time.time())
        # Sharing the same mods again gives the same code.
        row = self.db.execute("SELECT code FROM shares WHERE owner = ? AND digest = ?", (owner, digest)).fetchone()
        if row:
            self.db.execute("UPDATE shares SET used = ? WHERE code = ?", (now, row["code"]))
            self.db.commit()
            return {"code": row["code"]}
        while True:
            code = "SW-" + "".join(secrets.choice(CODE_LETTERS) for _ in range(4)) + "-" + \
                   "".join(secrets.choice(CODE_LETTERS) for _ in range(4))
            if not self.db.execute("SELECT 1 FROM shares WHERE code = ?", (code,)).fetchone():
                break
        self.db.execute("INSERT INTO shares VALUES (?, ?, ?, ?, ?, ?)", (code, owner, digest, text, now, now))
        self.db.commit()
        nick = self.nick_of(owner)
        log.info("%s shared %d mods as %s", nick, len(clean), code)
        notify.post(f"{nick} shared {len(clean)} mod{'s' if len(clean) != 1 else ''}: "
                    + ", ".join(m["name"] for m in clean[:5]) + (" ..." if len(clean) > 5 else ""), nick)
        return {"code": code}

    def get_share(self, code: str) -> dict:
        code = code.upper().replace(" ", "")
        if not code.startswith("SW-") and len(code) == 8:
            code = f"SW-{code[:4]}-{code[4:]}"
        row = self.db.execute("SELECT * FROM shares WHERE code = ?", (code,)).fetchone()
        if row is None:
            raise ModError(404, "There's no mod code like that. Check it and try again.")
        self.db.execute("UPDATE shares SET used = ? WHERE code = ?", (int(time.time()), code))
        self.db.commit()
        return {"code": code, "by": self.nick_of(row["owner"]), "mods": json.loads(row["body"])}

    def clean_up(self):
        """Removes shares nobody opened in KEEP_DAYS and files no share uses (a day after upload, so a
        share being put together isn't cut short)."""
        now = int(time.time())
        self.db.execute("DELETE FROM shares WHERE used < ?", (now - KEEP_DAYS * 86400,))
        used = set()
        for (body,) in self.db.execute("SELECT body FROM shares"):
            for mod in json.loads(body):
                used.update(f["sha256"] for f in mod["files"])
        stale = [r["hash"] for r in self.db.execute("SELECT hash FROM blobs WHERE created < ?", (now - 86400,))
                 if r["hash"] not in used]
        for digest in stale:
            try:
                os.remove(self.path(digest))
            except FileNotFoundError:
                pass
            self.db.execute("DELETE FROM blobs WHERE hash = ?", (digest,))
        self.db.commit()
        if stale:
            log.info("removed %d unused mod files", len(stale))

    async def clean_up_daily(self):
        while True:
            try:
                self.clean_up()
            except Exception:
                log.exception("mod clean-up failed")
            await asyncio.sleep(24 * 3600)
