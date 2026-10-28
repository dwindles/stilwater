"""GameSpy's HTTP web services that Saints Row 2 calls after signing in to Presence:

  AuthService  POST /AuthService/AuthService.asmx  login certificates (LoginProfile, LoginUniqueNick)
  Sake         POST /SakeStorageServer/StorageServer.asmx  per-player records (multiplayer storage)
               POST /SakeFileServer/upload.aspx, GET /SakeFileServer/download.aspx  files

The game reaches them as http://srow2pc.auth.pubsvs.openspy.net/... and the like, which the core
resolves to this server; nginx (server/nginx-stilwater-online.conf) passes those hostnames on port
80 to this HTTP server on 127.0.0.1:29980.

AuthService: the game RSA-encrypts the password (PKCS#1 v1.5) with a 1024-bit public key in the
exe (0x00DD0C78, which the core replaces with ours), and checks the certificate it gets back
against the same key: an MD5 of the certificate's fields, signed PKCS#1 v1.5. The private half is
/etc/stilwater-online/authservice.pem. Certificates also carry a peer key (peerkey.pem) the game
uses to sign itself to co-op partners."""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import struct
import time
import urllib.parse
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import gamespy as gs
import mods
import notify
from accounts import Accounts

log = logging.getLogger("web")

PORT = 29980
MAX_BODY = 4 * 1024 * 1024
CERT_SECONDS = 24 * 3600
SAKE_GAME_ID = 2110         # Saints Row 2's Sake game id
NS_AUTH = "http://gamespy.net/AuthService/"
NS_SAKE = "http://gamespy.net/sake"

# AuthService response codes.
LOGIN_SUCCESS, LOGIN_USER_NOT_FOUND, LOGIN_INVALID_PASSWORD, LOGIN_INVALID_PROFILE, LOGIN_SERVER_ERROR = 0, 2, 3, 4, 7
# Sake-File-Result header values.
FILE_SUCCESS, FILE_MISSING_PARAMETER, FILE_NOT_FOUND, FILE_TOO_LARGE = 0, 3, 4, 5


# --- RSA (1024-bit keys, PKCS#1 v1.5), enough for AuthService

class RsaKey:
    MD5_DIGEST_INFO = bytes.fromhex("3020300c06082a864886f70d020505000410")

    def __init__(self, n: int, e: int, d: int):
        self.n, self.e, self.d = n, e, d
        self.size = (n.bit_length() + 7) // 8

    @classmethod
    def load(cls, path: str) -> "RsaKey":
        """Reads a PEM private key (PKCS#1 'RSA PRIVATE KEY' or PKCS#8 'PRIVATE KEY')."""
        with open(path) as f:
            text = f.read()
        der = base64.b64decode("".join(line for line in text.splitlines() if line and not line.startswith("-----")))
        fields = _der_items(der)[0]
        if isinstance(fields[1], list):         # PKCS#8: version, algorithm, OCTET STRING with PKCS#1 inside
            fields = _der_items(fields[2])[0]
        return cls(fields[1], fields[2], fields[3])

    def hex(self, value: int) -> str:
        """Lowercase hex with an even number of digits, as the certificates carry numbers."""
        text = format(value, "x")
        return "0" * (len(text) % 2) + text

    def decrypt(self, ciphertext: bytes) -> bytes:
        block = pow(int.from_bytes(ciphertext, "big"), self.d, self.n).to_bytes(self.size, "big")
        end = block.find(b"\0", 2)
        if block[:2] != b"\0\2" or end < 10:
            raise ValueError("bad padding")
        return block[end + 1:]

    def sign_md5(self, data: bytes) -> bytes:
        digest = self.MD5_DIGEST_INFO + hashlib.md5(data).digest()
        block = b"\0\1" + b"\xff" * (self.size - 3 - len(digest)) + b"\0" + digest
        return pow(int.from_bytes(block, "big"), self.d, self.n).to_bytes(self.size, "big")


def _der_items(der: bytes) -> list:
    """The items in DER-encoded data: ints for INTEGERs, lists for SEQUENCEs, bytes for the rest."""
    items, at = [], 0
    while at < len(der):
        tag, length = der[at], der[at + 1]
        at += 2
        if length & 0x80:
            count = length & 0x7F
            length = int.from_bytes(der[at:at + count], "big")
            at += count
        value = der[at:at + length]
        at += length
        items.append(int.from_bytes(value, "big") if tag == 0x02 else _der_items(value) if tag == 0x30 else value)
    return items


# --- XML

def _strip(element: ET.Element) -> ET.Element:
    """Drops namespaces from every tag, so lookups go by local name."""
    for node in element.iter():
        if "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
        if ":" in node.tag:
            node.tag = node.tag.split(":", 1)[1]
    return element


def _text(parent, path: str, default: str = "") -> str:
    node = parent.find(path) if parent is not None else None
    return node.text or default if node is not None else default


def _envelope(namespace: str, body: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            f'xmlns:ns1="{namespace}"><SOAP-ENV:Body>{body}</SOAP-ENV:Body></SOAP-ENV:Envelope>').encode()


def _elements(*pairs) -> str:
    return "".join(f"<ns1:{name}>{escape(str(value))}</ns1:{name}>" if not isinstance(value, Raw) else
                   f"<ns1:{name}>{value}</ns1:{name}>" for name, value in pairs)


class Raw(str):
    """Already-built XML for _elements."""


# --- HTTP

class Request:
    def __init__(self, method: str, path: str, query: dict, headers: dict, body: bytes):
        self.method, self.path, self.query, self.headers, self.body = method, path, query, headers, body

    def arg(self, name: str) -> str:
        return self.query.get(name, [""])[0]


class Response:
    def __init__(self, status: int = 200, body: bytes = b"", content_type: str = "text/xml; charset=utf-8", headers=()):
        self.status, self.body, self.content_type, self.headers = status, body, content_type, list(headers)


REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large",
           500: "Internal Server Error"}


class WebServices:
    def __init__(self, presence, accounts: Accounts, data: str, keys: str, mod_files: str = ""):
        self.presence = presence
        self.accounts = accounts
        self.auth_key = self.peer_key = None
        try:
            self.auth_key = RsaKey.load(os.path.join(keys, "authservice.pem"))
            self.peer_key = RsaKey.load(os.path.join(keys, "peerkey.pem"))
        except (OSError, ValueError, IndexError) as e:
            log.warning("AuthService keys missing in %s (%s); in-game sign-in will fail", keys, e)
        self.sake = Sake(os.path.join(data, "sake.db"))
        self.mods = mods.ModStore(data, mod_files or os.path.join(data, "mod-files"),
                                  lambda owner: (accounts.profile(owner) or {"nick": f"#{owner}"})["nick"])

    async def start(self, bind: str):
        asyncio.create_task(self.mods.clean_up_daily())
        return await asyncio.start_server(self.serve, bind, PORT)

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = await asyncio.wait_for(self._read_head(reader), 30)
            method, target, headers = head
            url = urllib.parse.urlsplit(target)
            length = int(headers.get("content-length", "0") or 0)
            if url.path.startswith(mods.PREFIX):
                # Shared mods: a file upload is streamed to disk rather than read into memory.
                response = await self.mods_route(method, url.path, headers, length, reader)
            else:
                if length > MAX_BODY:
                    return
                body = await asyncio.wait_for(reader.readexactly(length), 30) if length else b""
                request = Request(method, url.path, urllib.parse.parse_qs(url.query), headers, body)
                try:
                    response = self.route(request)
                except Exception:
                    log.exception("%s %s failed", request.method, request.path)
                    response = Response(500)
            head = [f"HTTP/1.1 {response.status} {REASONS.get(response.status, 'OK')}",
                    f"Content-Type: {response.content_type}", f"Content-Length: {len(response.body)}", "Connection: close"]
            head += [f"{k}: {v}" for k, v in response.headers]
            writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + response.body)
            await writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    @staticmethod
    async def _read_head(reader: asyncio.StreamReader):
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
        lines = head.split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        return method, target, headers

    # --- shared mods (mods.py)

    async def mods_route(self, method: str, path: str, headers: dict, length: int, reader) -> Response:
        def reply(value, status=200):
            return Response(status, json.dumps(value).encode(), "application/json; charset=utf-8")

        async def small_body() -> bytes:
            if length > MAX_BODY:
                raise mods.ModError(413, "That request is too big.")
            return await asyncio.wait_for(reader.readexactly(length), 30) if length else b""

        def signed_in() -> int:
            owner = self.profile_for_ticket(headers.get("x-stilwater-ticket", ""))
            if not owner:
                raise mods.ModError(401, "Sign in again to share mods.")
            return owner

        rest = path[len(mods.PREFIX):]
        try:
            if method == "POST" and rest == "missing":
                signed_in()
                return reply(self.mods.missing(await small_body()))
            if method == "PUT" and rest.startswith("blob/"):
                owner = signed_in()
                return reply(await self.mods.receive(reader, rest[5:], length, owner))
            if method == "POST" and rest == "share":
                owner = signed_in()
                return reply(self.mods.share(await small_body(), owner))
            if method == "GET" and rest.startswith("share/"):
                return reply(self.mods.get_share(urllib.parse.unquote(rest[6:])))
            if method == "GET" and rest.startswith("file/") and mods.HASH.match(rest[5:]) and self.mods.has(rest[5:]):
                # nginx serves these itself; this is for running without it.
                with open(self.mods.path(rest[5:]), "rb") as f:
                    return Response(200, f.read(), "application/octet-stream")
            return reply({"error": "Not found."}, 404)
        except mods.ModError as e:
            return reply({"error": e.text}, e.status)
        except (ValueError, AttributeError, TypeError):
            return reply({"error": "That request couldn't be read."}, 400)

    def route(self, request: Request) -> Response:
        path = request.path.lower()
        action = request.headers.get("soapaction", "").strip('"').rsplit("/", 1)[-1]
        log.debug("%s %s %s", request.method, request.path, action)
        if path == "/authservice/authservice.asmx" and request.method == "POST":
            return self.auth(action, request.body)
        if path == "/sakestorageserver/storageserver.asmx" and request.method == "POST":
            return self.sake.soap(action, request.body, self.profile_for_ticket)
        if path == "/sakefileserver/upload.aspx" and request.method == "POST":
            return self.sake.upload(request)
        if path == "/sakefileserver/download.aspx" and request.method == "GET":
            return self.sake.download(request)
        log.info("unhandled web request %s %s %s (%d bytes)", request.method, request.path, action, len(request.body))
        return Response(404)

    def profile_for_ticket(self, ticket: str):
        return self.presence.tickets.get(ticket)

    # --- AuthService

    def auth(self, action: str, body: bytes) -> Response:
        if action not in ("LoginProfile", "LoginUniqueNick"):
            log.info("unhandled AuthService call %s", action)
            return Response(400)
        request = _strip(ET.fromstring(body)).find(f".//{action}")
        code, profile, certificate = LOGIN_SERVER_ERROR, None, ""
        if request is not None and self.auth_key:
            nick = _text(request, "profilenick" if action == "LoginProfile" else "uniquenick")
            profile = self.accounts.by_nick(nick)
            if profile is None or (action == "LoginProfile" and profile["email"].lower() != _text(request, "email").lower()):
                code, profile = LOGIN_USER_NOT_FOUND, None
            else:
                try:
                    password = self.auth_key.decrypt(bytes.fromhex(_text(request, "password/Value")))
                    if gs.md5(password.decode("latin-1")) == profile["password_md5"]:
                        code = LOGIN_SUCCESS
                        certificate = self.certificate(profile, int(_text(request, "partnercode", "0") or 0),
                                                       int(_text(request, "namespaceid", "1") or 1))
                    else:
                        code = LOGIN_INVALID_PASSWORD
                except ValueError:
                    code = LOGIN_INVALID_PASSWORD
        log.info("AuthService %s for %s: %s", action, profile["nick"] if profile else "?", code)
        parts = [("responseCode", code)]
        if code == LOGIN_SUCCESS:
            parts += [("peerkeyprivate", self.peer_key.hex(self.peer_key.d)), ("certificate", Raw(certificate))]
        return Response(body=_envelope(NS_AUTH, f"<ns1:{action}Result>{_elements(*parts)}</ns1:{action}Result>"))

    def certificate(self, profile, partner: int, namespace: int) -> str:
        nick = profile["nick"]
        cdkey_hash = hashlib.md5(b"").hexdigest().upper()
        modulus, exponent = self.peer_key.hex(self.peer_key.n), self.peer_key.hex(self.peer_key.e)
        server_data = secrets.token_bytes(128)
        numbers = (0, 1, partner, namespace, profile["user_id"], profile["id"], int(time.time()) + CERT_SECONDS)
        # What the game hashes to check the signature: the numbers little-endian, the strings, then
        # the peer key's modulus and exponent (big-endian, no leading zeros) and the server data.
        signed = struct.pack("<7I", *numbers) + (nick + nick + cdkey_hash).encode() + \
            bytes.fromhex(modulus) + bytes.fromhex(exponent) + server_data
        names = ("length", "version", "partnercode", "namespaceid", "userid", "profileid", "expiretime")
        return _elements(*zip(names, numbers), ("profilenick", nick), ("uniquenick", nick), ("cdkeyhash", cdkey_hash),
                         ("peerkeymodulus", modulus), ("peerkeyexponent", exponent), ("serverdata", server_data.hex()),
                         ("signature", self.auth_key.sign_md5(signed).hex().upper()))


# --- Sake

class Sake:
    """Sake storage: tables of records per game, each owned by a profile. Values keep the type
    they were written with (intValue, asciiStringValue, ...)."""
    RESERVED = ("recordid", "ownerid", "row", "num_ratings", "average_rating")

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY, game INTEGER NOT NULL, tableid TEXT NOT NULL, owner INTEGER NOT NULL,
                fields TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS records_owner ON records (game, tableid, owner);
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY, game INTEGER NOT NULL, owner INTEGER NOT NULL, name TEXT NOT NULL,
                data BLOB NOT NULL, created INTEGER NOT NULL);
        """)

    def soap(self, action: str, body: bytes, profile_for_ticket) -> Response:
        request = _strip(ET.fromstring(body)).find(f".//{action}")
        if request is None:
            return Response(400)
        handler = getattr(self, "do_" + action, None)
        if handler is None:
            log.info("unhandled Sake call %s", action)
            return Response(400)
        game = int(_text(request, "gameid", "0") or 0)
        owner = profile_for_ticket(_text(request, "loginTicket"))
        if owner is None:
            result, extra = "LoginTicketInvalid", ""
        else:
            result, extra = handler(request, game, owner)
        log.debug("Sake %s %s for %s: %s", action, _text(request, "tableid"), owner, result)
        return Response(body=_envelope(NS_SAKE, f"<ns1:{action}Response><ns1:{action}Result>{result}</ns1:{action}Result>"
                                                f"{extra}</ns1:{action}Response>"))

    @staticmethod
    def _fields(request) -> dict:
        """RecordField elements -> {name: [type, value]}."""
        fields = {}
        for field in request.findall("values/RecordField"):
            value = field.find("value")
            typed = value[0] if value is not None and len(value) else None
            if typed is not None:
                fields[_text(field, "name")] = [typed.tag, _text(typed, "value")]
        return fields

    def _records(self, rows, wanted: list) -> str:
        out = []
        for row_number, row in enumerate(rows, 1):
            stored = json.loads(row["fields"])
            values = []
            for name in wanted:
                if name in ("recordid", "ownerid", "row"):
                    number = {"recordid": row["id"], "ownerid": row["owner"], "row": row_number}[name]
                    values.append(f"<ns1:RecordValue><ns1:intValue><ns1:value>{number}</ns1:value></ns1:intValue></ns1:RecordValue>")
                elif name in ("num_ratings", "average_rating"):
                    kind = "intValue" if name == "num_ratings" else "floatValue"
                    values.append(f"<ns1:RecordValue><ns1:{kind}><ns1:value>0</ns1:value></ns1:{kind}></ns1:RecordValue>")
                elif name in stored:
                    kind, value = stored[name]
                    values.append(f"<ns1:RecordValue><ns1:{kind}><ns1:value>{escape(value)}</ns1:value></ns1:{kind}></ns1:RecordValue>")
                else:
                    values.append("<ns1:RecordValue><ns1:intValue><ns1:value>0</ns1:value></ns1:intValue></ns1:RecordValue>")
            out.append(f"<ns1:ArrayOfRecordValue>{''.join(values)}</ns1:ArrayOfRecordValue>")
        return f"<ns1:values>{''.join(out)}</ns1:values>"

    @staticmethod
    def _wanted(request) -> list:
        return [node.text or "" for node in request.findall("fields/string")]

    def do_CreateRecord(self, request, game, owner):
        cursor = self.db.execute("INSERT INTO records (game, tableid, owner, fields) VALUES (?, ?, ?, ?)",
                                 (game, _text(request, "tableid"), owner, json.dumps(self._fields(request))))
        return "Success", _elements(("recordid", cursor.lastrowid))

    def do_UpdateRecord(self, request, game, owner):
        row = self.db.execute("SELECT fields FROM records WHERE id = ? AND game = ? AND owner = ?",
                              (int(_text(request, "recordid", "0") or 0), game, owner)).fetchone()
        if row is None:
            return "RecordNotFound", ""
        fields = json.loads(row["fields"])
        fields.update(self._fields(request))
        self.db.execute("UPDATE records SET fields = ? WHERE id = ?", (json.dumps(fields), int(_text(request, "recordid"))))
        return "Success", ""

    def do_DeleteRecord(self, request, game, owner):
        self.db.execute("DELETE FROM records WHERE id = ? AND game = ? AND owner = ?",
                        (int(_text(request, "recordid", "0") or 0), game, owner))
        return "Success", ""

    def do_GetMyRecords(self, request, game, owner):
        rows = self.db.execute("SELECT * FROM records WHERE game = ? AND tableid = ? AND owner = ? ORDER BY id",
                               (game, _text(request, "tableid"), owner)).fetchall()
        return "Success", self._records(rows, self._wanted(request))

    def do_GetSpecificRecords(self, request, game, owner):
        ids = [int(node.text) for node in request.findall("recordids/int") if (node.text or "").isdigit()]
        rows = self.db.execute(f"SELECT * FROM records WHERE game = ? AND tableid = ? AND id IN ({','.join('?' * len(ids))}) ORDER BY id",
                               (game, _text(request, "tableid"), *ids)).fetchall() if ids else []
        return "Success", self._records(rows, self._wanted(request))

    def do_SearchForRecords(self, request, game, owner):
        rows = self.db.execute("SELECT * FROM records WHERE game = ? AND tableid = ? ORDER BY id",
                               (game, _text(request, "tableid"))).fetchall()
        owners = [int(node.text) for node in request.findall("ownerids/int") if (node.text or "").isdigit()]
        if owners:
            rows = [r for r in rows if r["owner"] in owners]
        rows = [r for r in rows if _matches(_text(request, "filter"), r)]
        offset = int(_text(request, "offset", "0") or 0)
        limit = int(_text(request, "max", "100") or 100)
        return "Success", self._records(rows[offset:offset + limit], self._wanted(request))

    def do_GetRecordCount(self, request, game, owner):
        rows = self.db.execute("SELECT * FROM records WHERE game = ? AND tableid = ?", (game, _text(request, "tableid"))).fetchall()
        return "Success", _elements(("count", sum(1 for r in rows if _matches(_text(request, "filter"), r))))

    def do_GetRecordLimit(self, request, game, owner):
        owned = self.db.execute("SELECT COUNT(*) FROM records WHERE game = ? AND tableid = ? AND owner = ?",
                                (game, _text(request, "tableid"), owner)).fetchone()[0]
        return "Success", _elements(("limitPerOwner", 1000), ("numOwned", owned))

    def do_RateRecord(self, request, game, owner):
        return "Success", _elements(("numRatings", 0), ("averageRating", 0))

    def do_GetRandomRecords(self, request, game, owner):
        return "Success", self._records([], self._wanted(request))

    # Files: one multipart upload, answered with Sake-File-Result (0 is success) and Sake-File-Id.

    def upload(self, request: Request) -> Response:
        game, owner = request.arg("gameid"), request.arg("pid")
        match = re.search(r'boundary="?([^";]+)', request.headers.get("content-type", ""))
        if not (game.isdigit() and owner.isdigit() and match):
            return Response(400, headers=[("Sake-File-Result", FILE_MISSING_PARAMETER)])
        name, data = _multipart_file(request.body, match.group(1).encode())
        if data is None:
            return Response(400, headers=[("Sake-File-Result", FILE_MISSING_PARAMETER)])
        if len(data) > MAX_BODY:
            return Response(413, headers=[("Sake-File-Result", FILE_TOO_LARGE)])
        file_id = self.db.execute("INSERT INTO files (game, owner, name, data, created) VALUES (?, ?, ?, ?, ?)",
                                  (int(game), int(owner), name, data, int(time.time()))).lastrowid
        if int(game) == SAKE_GAME_ID:
            self._saints_row_2_upload(int(owner), file_id)
        log.info("Sake file %d uploaded by %s (%s, %d bytes)", file_id, owner, name, len(data))
        return Response(200, b"", headers=[("Sake-File-Result", FILE_SUCCESS), ("Sake-File-Id", file_id)])

    def _saints_row_2_upload(self, owner: int, file_id: int):
        """SR2 uploads its multiplayer storage and later finds it through its user_file_storage record,
        which the service keeps (the game doesn't write it). Older copies are dropped."""
        fields = {"filename": ["asciiStringValue", "MPStorage"], "file_id": ["intValue", str(file_id)]}
        row = self.db.execute("SELECT id, fields FROM records WHERE game = ? AND tableid = 'user_file_storage' AND owner = ?",
                              (SAKE_GAME_ID, owner)).fetchone()
        if row:
            old = json.loads(row["fields"]).get("file_id", ["", "0"])[1]
            self.db.execute("UPDATE records SET fields = ? WHERE id = ?", (json.dumps(fields), row["id"]))
            self.db.execute("DELETE FROM files WHERE id = ? AND owner = ?", (int(old) if old.isdigit() else 0, owner))
        else:
            self.db.execute("INSERT INTO records (game, tableid, owner, fields) VALUES (?, 'user_file_storage', ?, ?)",
                            (SAKE_GAME_ID, owner, json.dumps(fields)))

    def download(self, request: Request) -> Response:
        file_id = request.arg("fileid")
        row = self.db.execute("SELECT name, data FROM files WHERE id = ?", (int(file_id),)).fetchone() if file_id.isdigit() else None
        if row is None:
            return Response(404, headers=[("Sake-File-Result", FILE_NOT_FOUND)])
        return Response(200, row["data"], "application/octet-stream",
                        [("Sake-File-Result", FILE_SUCCESS), ("Content-Disposition", f'attachment; filename="{row["name"]}"')])


def _multipart_file(body: bytes, boundary: bytes):
    """(filename, data) of the first part in a multipart/form-data body."""
    for part in body.split(b"--" + boundary)[1:]:
        head, _, data = part.partition(b"\r\n\r\n")
        if not data:
            continue
        name = re.search(rb'filename="([^"]*)"', head) or re.search(rb'name="([^"]*)"', head)
        return (name.group(1).decode("latin-1") if name else "file"), data[:-2] if data.endswith(b"\r\n") else data
    return None, None


def _matches(text: str, row) -> bool:
    """Sake filters are SQL-like ("ownerid = 5 and score > 10"). Comparisons on the reserved
    fields and on stored values are checked; anything else lets the record through."""
    if not text.strip():
        return True
    stored = json.loads(row["fields"])
    for clause in re.split(r"\s+and\s+", text.strip(), flags=re.I):
        match = re.fullmatch(r"\s*(\w+)\s*(=|==|!=|<>|<=|>=|<|>)\s*'?([^']*?)'?\s*", clause)
        if not match:
            continue
        name, op, want = match.groups()
        have = {"recordid": row["id"], "ownerid": row["owner"]}.get(name.lower(), stored.get(name, [None, None])[1])
        if have is None:
            continue
        try:
            have, want = float(have), float(want)
        except ValueError:
            have = str(have)
        ok = {"=": have == want, "==": have == want, "!=": have != want, "<>": have != want, "<": have < want,
              ">": have > want, "<=": have <= want, ">=": have >= want}[op]
        if not ok:
            return False
    return True
