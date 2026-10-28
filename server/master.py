"""The game list: hosts register with the master (Query & Reporting 2 over UDP 27900, which also
answers the game's availability check) and players fetch the list from the server browser
(TCP 28910), encrypted with gamespy.ListCipher.

Hosts are challenged from a second port first: if the reply comes back, the host's router lets
unsolicited packets in (port forwarded, UPnP, or an open NAT) and players connect to it directly;
otherwise the challenge is resent from the main port and players reach it through NAT
negotiation. Byte layouts were checked against the game's own parser (0x008E7EB0, 0x008E7D00)."""
import asyncio
import logging
import os
import re
import secrets
import socket
import string
import struct
import time

import gamespy as gs
import notify

log = logging.getLogger("master")

QR_PORT = 27900
PROBE_PORT = 27902
BROWSER_PORT = 28910
DEFAULT_QUERY_PORT = 6500
SERVER_TIMEOUT = 90
PROBE_WAIT = 2.0

# QR2 packet types.
QR_CHALLENGE, QR_HEARTBEAT, QR_CLIENT_MESSAGE, QR_CLIENT_MESSAGE_ACK, QR_KEEPALIVE, QR_AVAILABLE, QR_REGISTERED = 1, 3, 6, 7, 8, 9, 10
# Server browser requests and the server entry flags.
LIST_REQUEST, INFO_REQUEST, SEND_MESSAGE_REQUEST, KEEPALIVE_REPLY = 0, 1, 2, 3
PUSH_SERVER_MESSAGE = 2
NO_SERVER_LIST, ALTERNATE_SOURCE_IP, LIMIT_RESULT_COUNT = 0x02, 0x08, 0x80
UNSOLICITED_UDP, PRIVATE_IP, CONNECT_NEGOTIATE, NONSTANDARD_PORT, NONSTANDARD_PRIVATE_PORT, HAS_KEYS, HAS_FULL_RULES = \
    0x01, 0x02, 0x04, 0x10, 0x20, 0x40, 0x80


class Host:
    def __init__(self, address, instance: bytes):
        self.address = address
        self.instance = instance
        self.fields: dict[str, str] = {}
        self.seen = time.monotonic()
        self.registered = False
        self.open = False
        self.challenge = ""
        self.probed_at = 0.0
        self.challenged_direct = False

    def matches(self, game_name: str) -> bool:
        return self.registered and self.fields.get("gamename", gs.GAME_NAME) == game_name

    def entry(self, keys: list[str], full_rules: bool = False) -> bytes:
        """The host as a server list entry (flags, addresses, then values of the asked-for keys)."""
        ip, port = self.address
        flags = NONSTANDARD_PORT if port != DEFAULT_QUERY_PORT else 0
        local = b""
        local_ip = self.fields.get("localip0", "")
        try:
            local = socket.inet_aton(local_ip)
            flags |= PRIVATE_IP
            local_port = int(self.fields.get("localport", port) or port)
            if local_port != DEFAULT_QUERY_PORT:
                flags |= NONSTANDARD_PRIVATE_PORT
                local += struct.pack(">H", local_port)
        except (OSError, ValueError):
            local = b""
        if self.open:
            flags |= UNSOLICITED_UDP
        elif self.fields.get("natneg", "1") != "0":
            flags |= CONNECT_NEGOTIATE
        if full_rules:
            flags |= HAS_FULL_RULES
        elif keys:
            flags |= HAS_KEYS
        out = bytes([flags]) + socket.inet_aton(ip)
        if flags & NONSTANDARD_PORT:
            out += struct.pack(">H", port)
        out += local
        if full_rules:
            for key, value in self.fields.items():
                out += key.encode("latin-1", "replace") + b"\0" + value.encode("latin-1", "replace") + b"\0"
            out += b"\0"
        elif keys:
            for key in keys:
                out += b"\xff" + self.fields.get(key, "").encode("latin-1", "replace") + b"\0"
        return out


class Master:
    def __init__(self, nicks_at=lambda ip: []):
        self.hosts: dict[tuple, Host] = {}
        self.nicks_at = nicks_at        # who is signed in from an address, to name hosts in the feed
        self.transport: asyncio.DatagramTransport | None = None
        self.probe: asyncio.DatagramTransport | None = None

    async def start(self, bind: str):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: _Udp(self.datagram), local_addr=(bind, QR_PORT))
        self.probe, _ = await loop.create_datagram_endpoint(lambda: _Udp(lambda d, a: None), local_addr=(bind, PROBE_PORT))
        server = await asyncio.start_server(self.serve_browser, bind, BROWSER_PORT)
        asyncio.create_task(self._expire())
        return server

    # --- QR2

    def datagram(self, data: bytes, address):
        if not data:
            return
        kind = data[0]
        if kind == QR_AVAILABLE:
            self.transport.sendto(b"\xfe\xfd\x09\x00\x00\x00\x00", address)
            return
        if len(data) < 5:
            return
        instance = data[1:5]
        host = self.hosts.get(address)
        if kind == QR_HEARTBEAT:
            self._heartbeat(address, instance, data[5:])
        elif host is None:
            return
        elif kind == QR_CHALLENGE:
            # Any answer will do: we don't check the response against the secret key.
            host.seen = time.monotonic()
            if not host.registered:
                host.registered = True
                host.open = not host.challenged_direct
                log.info("host %s:%d registered (%s)", *address, "open" if host.open else "behind NAT")
                nicks = self.nicks_at(address[0])
                hostname = host.fields.get("hostname", "")
                notify.game_hosted(address[0], " & ".join(nicks) or hostname or "Someone", hostname, *nicks)
            self.transport.sendto(b"\xfe\xfd" + bytes([QR_REGISTERED]) + host.instance, address)
        elif kind in (QR_KEEPALIVE, QR_CLIENT_MESSAGE_ACK):
            host.seen = time.monotonic()

    def _heartbeat(self, address, instance: bytes, payload: bytes):
        fields = {}
        parts = payload.split(b"\0")
        for i in range(0, len(parts) - 1, 2):
            if not parts[i]:
                break
            fields[parts[i].decode("latin-1")] = parts[i + 1].decode("latin-1")
        host = self.hosts.get(address)
        if fields.get("statechanged") == "2":
            if host:
                log.info("host %s:%d closed", *address)
                notify.game_closed(address[0])
                del self.hosts[address]
            return
        if host is None or host.instance != instance:
            host = self.hosts[address] = Host(address, instance)
        host.fields.update(fields)
        host.seen = time.monotonic()
        if not host.registered and (not host.probed_at or host.challenged_direct):
            host.challenge = "".join(secrets.choice(string.ascii_letters) for _ in range(6)) + "00" + \
                socket.inet_aton(address[0]).hex().upper() + f"{address[1]:04X}"
            if not host.probed_at:
                host.probed_at = time.monotonic()
                self.probe.sendto(self._challenge_packet(host), address)
                asyncio.get_running_loop().call_later(PROBE_WAIT, self._challenge_directly, host)
            else:
                self.transport.sendto(self._challenge_packet(host), address)

    def _challenge_packet(self, host: Host) -> bytes:
        return b"\xfe\xfd" + bytes([QR_CHALLENGE]) + host.instance + host.challenge.encode() + b"\0"

    def _challenge_directly(self, host: Host):
        if not host.registered and self.hosts.get(host.address) is host:
            host.challenged_direct = True
            self.transport.sendto(self._challenge_packet(host), host.address)

    def send_to_host(self, ip: bytes, port: int, data: bytes):
        """Passes a player's message (in practice a NAT negotiation cookie) to the host."""
        host = self.hosts.get((socket.inet_ntoa(ip), port))
        if host:
            self.transport.sendto(b"\xfe\xfd" + bytes([QR_CLIENT_MESSAGE]) + host.instance + os.urandom(4) + data, host.address)

    async def _expire(self):
        while True:
            await asyncio.sleep(15)
            now = time.monotonic()
            for address, host in list(self.hosts.items()):
                if now - host.seen > SERVER_TIMEOUT:
                    notify.game_closed(address[0])
                    del self.hosts[address]

    # --- server browser

    async def serve_browser(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        cipher = None
        buffer = b""
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), 120)
                if not chunk:
                    break
                buffer += chunk
                while len(buffer) >= 2:
                    length = struct.unpack(">H", buffer[:2])[0]
                    if length < 3 or length > 8192:
                        return
                    if len(buffer) < length:
                        break
                    request, buffer = buffer[2:length], buffer[length:]
                    kind = request[0]
                    if kind == LIST_REQUEST:
                        cipher = self._list(writer, peer, request, cipher)
                    elif kind == INFO_REQUEST and cipher and len(request) >= 7:
                        host = self.hosts.get((socket.inet_ntoa(request[1:5]), struct.unpack(">H", request[5:7])[0]))
                        if host and host.registered:
                            body = bytes([PUSH_SERVER_MESSAGE]) + host.entry([], full_rules=True)
                            writer.write(cipher.encrypt(struct.pack(">H", len(body) + 2) + body))
                    elif kind == SEND_MESSAGE_REQUEST and len(request) > 7:
                        self.send_to_host(request[1:5], struct.unpack(">H", request[5:7])[0], request[7:])
                await writer.drain()
        except (asyncio.TimeoutError, ConnectionError, ValueError, struct.error, IndexError) as e:
            log.debug("browser %s: %s", peer, e)
        finally:
            writer.close()

    def _list(self, writer, peer, request: bytes, cipher):
        p = 7
        game_for, p = _nts(request, p)
        game_from, p = _nts(request, p)
        client_challenge = request[p:p + 8]
        p += 8
        filter_text, p = _nts(request, p)
        keys_text, p = _nts(request, p)
        options = struct.unpack(">I", request[p:p + 4])[0]
        p += 4
        source_ip = socket.inet_aton(peer[0])
        if options & ALTERNATE_SOURCE_IP:
            source_ip = request[p:p + 4]
            p += 4
        limit = struct.unpack(">I", request[p:p + 4])[0] if options & LIMIT_RESULT_COUNT else 10000
        keys = [k for k in keys_text.split("\\") if k]

        if cipher is None:
            # Two bytes of backend flags (none) lead the crypt challenge; the game reads them at +1.
            crypt_challenge = b"\0\0" + os.urandom(8)
            server_challenge = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(25)).encode()
            writer.write(bytes([len(crypt_challenge) ^ 0xEC]) + crypt_challenge +
                         bytes([len(server_challenge) ^ 0xEA]) + server_challenge)
            cipher = gs.ListCipher(client_challenge, server_challenge)

        body = source_ip + struct.pack(">H", DEFAULT_QUERY_PORT)
        if not options & NO_SERVER_LIST:
            body += bytes([len(keys)])
            for key in keys:
                body += b"\0" + key.encode("latin-1", "replace") + b"\0"
            body += b"\0"                                  # no popular values
            matcher = Filter(filter_text)
            hosts = [h for h in self.hosts.values() if h.matches(game_for) and matcher.matches(h.fields)][:limit]
            for host in hosts:
                body += host.entry(keys)
            body += b"\0\xff\xff\xff\xff"
            log.info("list for %s (%s): %d hosts, filter %r", peer[0], game_for, len(hosts), filter_text)
        writer.write(cipher.encrypt(body))
        return cipher


def _nts(data: bytes, start: int) -> tuple[str, int]:
    end = data.index(b"\0", start)
    return data[start:end].decode("latin-1"), end + 1


class _Udp(asyncio.DatagramProtocol):
    def __init__(self, handler):
        self.handler = handler

    def datagram_received(self, data, address):
        try:
            self.handler(data, address)
        except Exception:
            log.exception("udp packet from %s", address)


class Filter:
    """The SQL-like filter the game sends with a list request ("gamemode = 'coop' and
    numplayers < maxplayers"). Anything it can't parse lets every host through."""
    TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|'((?:[^']|'')*)'|(<>|!=|<=|>=|==|=|<|>|\(|\))|([A-Za-z_][A-Za-z0-9_]*))")

    def __init__(self, text: str):
        self.tree = None
        try:
            self.tokens = self._tokenize(text)
            self.at = 0
            if self.tokens:
                self.tree = self._or()
                if self.at != len(self.tokens):
                    raise ValueError("trailing tokens")
        except (ValueError, IndexError):
            log.info("filter not understood, ignoring it: %r", text)
            self.tree = None

    def matches(self, fields: dict) -> bool:
        if self.tree is None:
            return True
        try:
            return bool(self._eval(self.tree, fields))
        except (ValueError, TypeError):
            return True

    def _tokenize(self, text):
        tokens, at = [], 0
        text = text.strip()
        while at < len(text):
            m = self.TOKEN.match(text, at)
            if not m or m.end() == at:
                raise ValueError(text[at:])
            number, quoted, op, word = m.groups()
            if number is not None:
                tokens.append(("value", number))
            elif quoted is not None:
                tokens.append(("value", quoted.replace("''", "'")))
            elif op is not None:
                tokens.append(("op", op))
            else:
                lowered = word.lower()
                tokens.append(("op", lowered) if lowered in ("and", "or", "not", "like") else ("key", word))
            at = m.end()
        return tokens

    def _peek(self, *ops):
        return self.at < len(self.tokens) and self.tokens[self.at][0] == "op" and self.tokens[self.at][1] in ops

    def _or(self):
        node = self._and()
        while self._peek("or"):
            self.at += 1
            node = ("or", node, self._and())
        return node

    def _and(self):
        node = self._not()
        while self._peek("and"):
            self.at += 1
            node = ("and", node, self._not())
        return node

    def _not(self):
        if self._peek("not"):
            self.at += 1
            return ("not", self._not())
        if self._peek("("):
            self.at += 1
            node = self._or()
            if not self._peek(")"):
                raise ValueError(")")
            self.at += 1
            return node
        left = self.tokens[self.at]
        self.at += 1
        negate = False
        if self._peek("not"):
            negate = True
            self.at += 1
        op = self.tokens[self.at]
        if op[0] != "op" or op[1] not in ("=", "==", "!=", "<>", "<", ">", "<=", ">=", "like"):
            raise ValueError(op)
        self.at += 1
        right = self.tokens[self.at]
        self.at += 1
        node = ("cmp", op[1], left, right)
        return ("not", node) if negate else node

    def _eval(self, node, fields):
        kind = node[0]
        if kind == "or":
            return self._eval(node[1], fields) or self._eval(node[2], fields)
        if kind == "and":
            return self._eval(node[1], fields) and self._eval(node[2], fields)
        if kind == "not":
            return not self._eval(node[1], fields)
        _, op, left, right = node
        a = fields.get(left[1], "") if left[0] == "key" else left[1]
        b = fields.get(right[1], "") if right[0] == "key" else right[1]
        if op == "like":
            pattern = "^" + re.escape(b).replace("%", ".*").replace("_", ".") + "$"
            return re.match(pattern, a, re.IGNORECASE) is not None
        try:
            a, b = float(a), float(b)
        except ValueError:
            a, b = a.lower(), b.lower()
        return {"=": a == b, "==": a == b, "!=": a != b, "<>": a != b,
                "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
