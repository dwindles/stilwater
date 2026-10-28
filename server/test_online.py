"""End-to-end check of a running Stilwater Online server, acting as two players and a host the way
the game's GameSpy code does.

    python test_online.py [host] [web port]

The web services are checked through port 80 (nginx) unless another port is given, e.g. 29980 for
a server running locally. STILWATER_AUTH_KEY overrides the AuthService public key (hex modulus).
"""
import base64
import hashlib
import http.client
import os
import re
import secrets
import socket
import struct
import sys
import time

import gamespy as gs

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
WEB_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 80
AUTH_KEY = int(os.environ.get("STILWATER_AUTH_KEY", gs.AUTH_PUBLIC_KEY), 16)


class Player:
    def __init__(self, nick: str, email: str, password: str):
        self.nick, self.email, self.password = nick, email, password
        self.sock = None
        self.buffer = b""
        self.profile_id = 0
        self.session_key = 0

    def connect(self):
        self.sock = socket.create_connection((HOST, 29900), timeout=5)
        command, fields = self.read()
        assert command == "lc" and fields["lc"] == "1", (command, fields)
        return fields["challenge"]

    def read(self):
        while b"\\final\\" not in self.buffer:
            chunk = self.sock.recv(4096)
            assert chunk, "connection closed"
            self.buffer += chunk
        end = self.buffer.index(b"\\final\\") + 7
        text, self.buffer = self.buffer[:end].decode("latin-1"), self.buffer[end:]
        return gs.parse(text)

    def read_until(self, command, text="", **match):
        deadline = time.time() + 5
        while time.time() < deadline:
            got, fields = self.read()
            if got == command and all(fields.get(k) == str(v) for k, v in match.items()) and text in fields.get("msg", ""):
                return fields
        raise AssertionError(f"{self.nick} never got {command} {match}")

    def send(self, *pairs):
        self.sock.sendall(gs.message(*pairs))

    def create(self):
        self.connect()
        self.send(("newuser", ""), ("email", self.email), ("nick", self.nick),
                  ("passwordenc", gs.encode_password(self.password)), ("productid", gs.PRODUCT_ID),
                  ("gamename", gs.GAME_NAME), ("namespaceid", 1), ("uniquenick", ""), ("partnerid", 0), ("id", 1))
        command, fields = self.read()
        assert command == "nur", (command, fields)
        self.sock.close()

    def login(self, launcher: bool = False):
        server_challenge = self.connect()
        client_challenge = gs.challenge(32)
        user = f"{self.nick}@{self.email}"
        password_md5 = gs.md5(self.password)
        self.send(("login", ""), ("challenge", client_challenge), ("user", user), ("partnerid", 0),
                  ("response", gs.login_hash(password_md5, user, client_challenge, server_challenge)),
                  ("firewall", 1), ("port", 0), ("productid", gs.PRODUCT_ID), ("gamename", gs.GAME_NAME),
                  ("namespaceid", 1), ("sdkrevision", 11), ("quiet", 0), *([("swlauncher", 1)] if launcher else []), ("id", 1))
        command, fields = self.read()
        assert command == "lc" and fields["lc"] == "2", (command, fields)
        assert fields["proof"] == gs.login_hash(password_md5, user, server_challenge, client_challenge), "bad proof"
        self.profile_id = int(fields["profileid"])
        self.session_key = int(fields["sesskey"])
        self.ticket = fields["lt"]
        bdy = self.read_until("bdy")
        return bdy


def search(nick: str) -> int:
    with socket.create_connection((HOST, 29901), timeout=5) as s:
        s.sendall(gs.message(("search", ""), ("sesskey", 0), ("profileid", 0), ("namespaceid", 1), ("nick", nick),
                             ("gamename", gs.GAME_NAME)))
        data = b""
        while b"\\final\\" not in data:
            data += s.recv(4096)
    _, fields = gs.parse(data.decode("latin-1"))
    return int(fields["bsr"])


def soap(host: str, path: str, namespace: str, action: str, body: str) -> str:
    envelope = ('<?xml version="1.0" encoding="UTF-8"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
                f'xmlns:ns1="{namespace}"><SOAP-ENV:Body><ns1:{action}>{body}</ns1:{action}></SOAP-ENV:Body></SOAP-ENV:Envelope>')
    web = http.client.HTTPConnection(HOST, WEB_PORT, timeout=10)
    web.request("POST", path, envelope.encode(), {"Host": host, "SOAPAction": f'"{namespace.rstrip("/")}/{action}"',
                                                   "Content-Type": "text/xml", "User-Agent": "GameSpyHTTP/1.0"})
    reply = web.getresponse()
    assert reply.status == 200, (path, action, reply.status)
    return reply.read().decode()


def xml_value(xml: str, name: str) -> str:
    match = re.search(rf"<(?:\w+:)?{name}>([^<]*)</", xml)
    return match.group(1) if match else ""


def rsa_encrypt(message: bytes) -> bytes:
    """PKCS#1 v1.5 encryption with the AuthService public key, as the game sends its password."""
    padding = bytes(secrets.choice(range(1, 256)) for _ in range(128 - 3 - len(message)))
    return pow(int.from_bytes(b"\0\2" + padding + b"\0" + message, "big"), 65537, AUTH_KEY).to_bytes(128, "big")


def certificate_valid(xml: str) -> bool:
    """The game's check: an MD5 of the certificate fields, signed with the AuthService key."""
    numbers = [int(xml_value(xml, n)) for n in ("length", "version", "partnercode", "namespaceid", "userid", "profileid", "expiretime")]
    data = struct.pack("<7I", *numbers) + (xml_value(xml, "profilenick") + xml_value(xml, "uniquenick") + xml_value(xml, "cdkeyhash")).encode()
    data += bytes.fromhex(xml_value(xml, "peerkeymodulus")) + bytes.fromhex(xml_value(xml, "peerkeyexponent")) + bytes.fromhex(xml_value(xml, "serverdata"))
    block = pow(int(xml_value(xml, "signature"), 16), 65537, AUTH_KEY).to_bytes(128, "big")
    return block.startswith(b"\0\1\xff") and block.endswith(hashlib.md5(data).digest())


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        sys.exit(1)


def main():
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(3)
    udp.sendto(b"\x09\x00\x00\x00\x00" + gs.GAME_NAME.encode() + b"\0", (HOST, 27900))
    check("availability", udp.recvfrom(64)[0] == b"\xfe\xfd\x09\x00\x00\x00\x00")

    tag = secrets.token_hex(3)
    a = Player(f"testa_{tag}", f"a_{tag}@example.com", "hunter22")
    b = Player(f"testb_{tag}", f"b_{tag}@example.com", "hunter33")
    a.create()
    b.create()
    a.login()
    b.login()
    check("accounts and sign-in (proof matches)", a.profile_id and b.profile_id)

    w = Player(a.nick, a.email, "nope")
    try:
        w.login()
        check("wrong password refused", False)
    except AssertionError as e:
        check("wrong password refused", "error" in str(e))

    check("search by nick", search(b.nick) == b.profile_id)
    a.send(("addbuddy", ""), ("sesskey", a.session_key), ("newprofileid", b.profile_id), ("reason", "co-op?"))
    request = b.read_until("bm", bm=2)
    check("friend request delivered", request["f"] == str(a.profile_id) and "|signed|" in request["msg"])
    b.send(("authadd", ""), ("sesskey", b.session_key), ("fromprofileid", a.profile_id), ("sig", request["msg"].split("|signed|")[1]))
    a.read_until("bm", bm=4)
    check("request accepted", True)
    b.send(("status", 1), ("sesskey", b.session_key), ("statstring", "Playing co-op"), ("locstring", "here"))
    a.read_until("bm", "Playing co-op", bm=100, f=b.profile_id)
    check("status reaches friend", True)
    # b also signs in from the launcher; the game session (b) stays signed in.
    bl = Player(b.nick, b.email, b.password)
    bl.login(launcher=True)
    a.send(("bm", 1), ("sesskey", a.session_key), ("t", b.profile_id), ("msg", "STILWATER_INVITE|" + a.nick))
    check("invite message reaches the launcher", bl.read_until("bm", bm=1)["msg"].startswith("STILWATER_INVITE|"))
    a.send(("status", 1), ("sesskey", a.session_key), ("statstring", "In the menus"), ("locstring", ""))
    b.read_until("bm", "In the menus", bm=100, f=a.profile_id)
    check("game stays signed in beside the launcher", True)
    b_game, b = b, bl
    a.send(("getprofile", ""), ("sesskey", a.session_key), ("profileid", b.profile_id), ("id", 7))
    check("getprofile", a.read_until("pi")["nick"] == b.nick)

    # Profile pictures and bios (launcher extensions; a stays a game session, b is b's launcher).
    picture = b"\xff\xd8\xff\xe0" + secrets.token_bytes(3000)
    a.send(("swsetprofile", ""), ("sesskey", a.session_key), ("bio", "Stilwater test"),
           ("avatar", base64.b64encode(picture).decode()), ("id", 8))
    digest = a.read_until("swprofile")["hash"]
    check("profile picture saved", len(digest) == 16)
    check("friend told the picture changed", b.read_until("swprofilechanged", profileid=a.profile_id)["hash"] == digest)
    b.send(("swgetprofile", ""), ("sesskey", b.session_key), ("profileid", a.profile_id), ("have", ""), ("id", 9))
    got = b.read_until("swprofile", profileid=a.profile_id)
    check("profile read back", base64.b64decode(got["avatar"]) == picture and got["bio"] == "Stilwater test")
    b.send(("swgetprofile", ""), ("sesskey", b.session_key), ("profileid", a.profile_id), ("have", digest), ("id", 10))
    check("cached picture not sent again", "avatar" not in b.read_until("swprofile", profileid=a.profile_id))
    a.send(("swsetprofile", ""), ("sesskey", a.session_key), ("avatar", base64.b64encode(b"GIF89a....").decode()), ("id", 11))
    check("non-image picture refused", "error" in a.read_until("error", id=11))

    # A host registers through QR2.
    host = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    host.bind(("0.0.0.0", 0))
    host.settimeout(5)
    instance = secrets.token_bytes(4)
    keys = {"gamename": gs.GAME_NAME, "hostname": f"test host {tag}", "gamemode": "coop", "numplayers": "1",
            "maxplayers": "2", "localip0": "192.168.1.50", "localport": "6500", "natneg": "1", "statechanged": "3"}
    payload = b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in keys.items()) + b"\0"
    host.sendto(b"\x03" + instance + payload, (HOST, 27900))
    registered = False
    deadline = time.time() + 6
    while time.time() < deadline and not registered:
        data, _ = host.recvfrom(1024)
        if data[:3] == b"\xfe\xfd\x01":
            host.sendto(b"\x01" + instance + b"0123456789abcdef\0", (HOST, 27900))
        elif data[:3] == b"\xfe\xfd\x0a":
            registered = True
    check("host registered", registered)
    b.send(("swjoin", ""), ("sesskey", b.session_key), ("profileid", a.profile_id), ("id", 12))
    check("accepting an invite pins the joiner's list", b.read_until("swjoined", id=12)["profileid"] == str(a.profile_id))

    # A player fetches the list.
    sb = socket.create_connection((HOST, 28910), timeout=5)
    client_challenge = secrets.token_bytes(8)
    fields = "\\hostname\\gamemode\\numplayers\\maxplayers"
    request = b"\x00\x01\x03" + struct.pack(">I", 0) + gs.GAME_NAME.encode() + b"\0" + gs.GAME_NAME.encode() + b"\0" + \
        client_challenge + b"gamemode = 'coop' and numplayers < maxplayers\0" + fields.encode() + b"\0" + struct.pack(">I", 0)
    sb.sendall(struct.pack(">H", len(request) + 2) + request)
    data = b""
    deadline = time.time() + 5
    plain = b""
    cipher = None
    while time.time() < deadline and not plain.endswith(b"\0\xff\xff\xff\xff"):
        data += sb.recv(8192)
        if cipher is None and len(data) > 1:
            a_len = (data[0] ^ 0xEC) + 2
            if len(data) < a_len:
                continue
            b_len = data[a_len - 1] ^ 0xEA
            if len(data) < a_len + b_len:
                continue
            cipher = gs.ListCipher(client_challenge, data[a_len:a_len + b_len])
            data = data[a_len + b_len:]
        if cipher:
            plain += cipher.decrypt(data)
            data = b""
    check("list decrypts", plain.endswith(b"\0\xff\xff\xff\xff"))
    p = 6
    count = plain[p]
    p += 1
    names = []
    for _ in range(count):
        p += 1
        end = plain.index(b"\0", p)
        names.append(plain[p:end].decode())
        p = end + 1
    p += 1                                     # popular values
    found = None
    while plain[p:p + 5] != b"\0\xff\xff\xff\xff":
        flags = plain[p]
        ip = socket.inet_ntoa(plain[p + 1:p + 5])
        p += 5
        port = struct.unpack(">H", plain[p:p + 2])[0] if flags & 0x10 else 6500
        p += 2 if flags & 0x10 else 0
        p += 4 if flags & 0x02 else 0
        p += 2 if flags & 0x20 else 0
        p += 4 if flags & 0x08 else 0
        values = {}
        if flags & 0x40:
            for name in names:
                assert plain[p] == 0xFF
                end = plain.index(b"\0", p + 1)
                values[name] = plain[p + 1:end].decode()
                p = end + 1
        if values.get("hostname") == keys["hostname"]:
            found = (ip, port, flags, values)
    check("host listed with its keys", found is not None and found[3]["gamemode"] == "coop")

    # The player asks the host to NAT-negotiate, through the browser.
    cookie = secrets.token_bytes(4)
    message = b"\xfd\xfc\x1e\x66\x6a\xb2\x02" + cookie
    ip, port = found[0], found[1]
    send = b"\x02" + socket.inet_aton(ip) + struct.pack(">H", port) + message
    sb.sendall(struct.pack(">H", len(send) + 2) + send)
    got = None
    deadline = time.time() + 5
    while time.time() < deadline:
        data, _ = host.recvfrom(1024)
        if data[:3] == b"\xfe\xfd\x06":
            got = data[11:]
            break
    check("player's message reaches host", got == message)

    # Both sides negotiate.
    def endpoint():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", 0))
        s.settimeout(5)
        return s
    sockets = {index: (endpoint(), endpoint()) for index in (0, 1)}
    for index, (game, nego) in sockets.items():
        for port_type, s in ((0, game), (1, nego), (2, nego), (3, nego)):
            init = b"\xfd\xfc\x1e\x66\x6a\xb2\x03\x00" + cookie + bytes([port_type, index, 1]) + \
                socket.inet_aton("192.168.1.2") + struct.pack(">H", s.getsockname()[1]) + gs.GAME_NAME.encode() + b"\0"
            s.sendto(init, (HOST, 27901))
    connects = {}
    for index, (game, nego) in sockets.items():
        deadline = time.time() + 5
        while time.time() < deadline and index not in connects:
            data, _ = nego.recvfrom(256)
            if data[7] == 5:
                connects[index] = (socket.inet_ntoa(data[12:16]), struct.unpack(">H", data[16:18])[0])
                nego.sendto(data[:7] + b"\x06" + data[8:12] + bytes([0, index]), (HOST, 27901))
    expected = {i: sockets[1 - i][0].getsockname()[1] for i in (0, 1)}
    check("NAT negotiation pairs the players", len(connects) == 2 and all(connects[i][1] == expected[i] for i in (0, 1)))

    keys["statechanged"] = "2"
    payload = b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in keys.items()) + b"\0"
    host.sendto(b"\x03" + instance + payload, (HOST, 27900))

    auth = "srow2pc.auth.pubsvs.openspy.net", "/AuthService/AuthService.asmx", "http://gamespy.net/AuthService/"
    def login_profile(player, password):
        return soap(*auth, "LoginProfile",
                    f"<ns1:version>1</ns1:version><ns1:partnercode>0</ns1:partnercode><ns1:namespaceid>1</ns1:namespaceid>"
                    f"<ns1:email>{player.email}</ns1:email><ns1:profilenick>{player.nick}</ns1:profilenick>"
                    f"<ns1:password><ns1:Value>{rsa_encrypt(password.encode()).hex()}</ns1:Value></ns1:password>")
    reply = login_profile(a, a.password)
    check("AuthService certificate", xml_value(reply, "responseCode") == "0" and xml_value(reply, "profileid") == str(a.profile_id))
    check("certificate signature verifies", certificate_valid(reply))
    modulus, private = int(xml_value(reply, "peerkeymodulus"), 16), int(xml_value(reply, "peerkeyprivate"), 16)
    check("peer key pair matches", pow(pow(12345, int(xml_value(reply, "peerkeyexponent"), 16), modulus), private, modulus) == 12345)
    check("AuthService refuses a wrong password", xml_value(login_profile(a, "nope"), "responseCode") == "3")

    sake = "srow2pc.sake.openspy.net", "/SakeStorageServer/StorageServer.asmx", "http://gamespy.net/sake"
    head = f"<ns1:gameid>2110</ns1:gameid><ns1:secretKey>x</ns1:secretKey><ns1:loginTicket>{a.ticket}</ns1:loginTicket>"
    reply = soap(*sake, "CreateRecord", head + "<ns1:tableid>stats</ns1:tableid><ns1:values><ns1:RecordField><ns1:name>score</ns1:name>"
                 "<ns1:value><ns1:intValue><ns1:value>42</ns1:value></ns1:intValue></ns1:value></ns1:RecordField></ns1:values>")
    check("Sake record created", xml_value(reply, "CreateRecordResult") == "Success" and xml_value(reply, "recordid").isdigit())
    reply = soap(*sake, "GetMyRecords", head + "<ns1:tableid>stats</ns1:tableid><ns1:fields><ns1:string>recordid</ns1:string>"
                 "<ns1:string>score</ns1:string></ns1:fields>")
    check("Sake record read back", "<ns1:value>42</ns1:value>" in reply)

    web = http.client.HTTPConnection(HOST, WEB_PORT, timeout=10)
    boundary = "----stilwater" + secrets.token_hex(4)
    upload = (f'--{boundary}\r\nContent-Disposition: form-data; name="MPStorage"; filename="MPStorage"\r\n'
              f"Content-Type: application/octet-stream\r\n\r\n").encode() + b"\x01\x02stilwater" + f"\r\n--{boundary}--\r\n".encode()
    web.request("POST", f"/SakeFileServer/upload.aspx?gameid=2110&pid={a.profile_id}", upload,
                {"Host": "srow2pc.sake.openspy.net", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    reply = web.getresponse()
    reply.read()
    file_id = reply.getheader("Sake-File-Id")
    check("Sake file uploaded", reply.status == 200 and reply.getheader("Sake-File-Result") == "0" and file_id)
    web = http.client.HTTPConnection(HOST, WEB_PORT, timeout=10)
    web.request("GET", f"/SakeFileServer/download.aspx?fileid={file_id}&gameid=2110&pid={a.profile_id}",
                headers={"Host": "srow2pc.sake.openspy.net"})
    check("Sake file downloaded", web.getresponse().read() == b"\x01\x02stilwater")
    reply = soap(*sake, "SearchForRecords", head + "<ns1:tableid>user_file_storage</ns1:tableid><ns1:filter></ns1:filter>"
                 f"<ns1:ownerids><ns1:int>{a.profile_id}</ns1:int></ns1:ownerids>"
                 "<ns1:fields><ns1:string>file_id</ns1:string></ns1:fields>")
    check("SR2 storage record points at the file", f"<ns1:value>{file_id}</ns1:value>" in reply)
    print("all checks passed")


if __name__ == "__main__":
    main()
