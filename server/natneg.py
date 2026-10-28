"""NAT negotiation (UDP 27901): introduces a joining player and a host who are both behind routers.

Both sides send INIT packets carrying the same cookie (the joiner passes it to the host through
the server browser and the master) from their game socket (port type 0) and from a negotiation
socket (port types 1-3, to natneg1/2/3, which are all this server). Once both are in, each gets a
CONNECT with the other's public address as seen here, and they punch through to each other."""
import asyncio
import logging
import socket
import struct
import time

import notify

log = logging.getLogger("natneg")

PORT = 27901
MAGIC = b"\xfd\xfc\x1e\x66\x6a\xb2"
INIT, INIT_ACK, CONNECT, CONNECT_ACK, ADDRESS_CHECK, ADDRESS_REPLY, REPORT, REPORT_ACK = 0, 1, 5, 6, 10, 11, 13, 14
GAME_PORT, NEGOTIATION_PORT = 0, 1
# Once both players are in, wait this long for their game-port INITs before going with what we have.
SETTLE_SECONDS = 1.5
RESEND_SECONDS = 1.0
SESSION_SECONDS = 60


class Client:
    def __init__(self):
        self.addresses: dict[int, tuple] = {}   # port type -> where that INIT came from
        self.use_game_port = False
        self.acked = False

    def public(self):
        """The address the other player should punch towards."""
        if self.use_game_port and GAME_PORT in self.addresses:
            return self.addresses[GAME_PORT]
        return self.addresses.get(NEGOTIATION_PORT) or next(iter(self.addresses.values()))

    def reply_to(self):
        """Where this player listens for CONNECT: its negotiation socket."""
        return self.addresses.get(NEGOTIATION_PORT) or self.addresses.get(GAME_PORT) or next(iter(self.addresses.values()))

    def ready(self) -> bool:
        return NEGOTIATION_PORT in self.addresses and (not self.use_game_port or GAME_PORT in self.addresses)


class Session:
    def __init__(self, cookie: bytes, version: int):
        self.cookie = cookie
        self.version = version
        self.clients: dict[int, Client] = {}
        self.started = time.monotonic()
        self.both_since = 0.0
        self.connecting = False


class NatNeg(asyncio.DatagramProtocol):
    def __init__(self, nicks_at=lambda ip: []):
        self.sessions: dict[bytes, Session] = {}
        self.transport = None
        self.nicks_at = nicks_at        # who is signed in from an address, to name players in the feed

    async def start(self, bind: str):
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self, local_addr=(bind, PORT))
        asyncio.create_task(self._expire())

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, address):
        if len(data) < 12 or data[:6] != MAGIC:
            return
        version, kind, cookie = data[6], data[7], data[8:12]
        if kind == INIT and len(data) >= 15:
            self._init(data, address, version, cookie)
        elif kind == CONNECT_ACK and len(data) >= 14:
            session = self.sessions.get(cookie)
            client = session and session.clients.get(data[13])
            if client:
                client.acked = True
        elif kind == REPORT:
            self.transport.sendto(data[:7] + bytes([REPORT_ACK]) + data[8:], address)
        elif kind == ADDRESS_CHECK and len(data) >= 15:
            ip = socket.inet_aton(address[0])
            self.transport.sendto(data[:7] + bytes([ADDRESS_REPLY]) + cookie + data[12:15] + ip + struct.pack(">H", address[1]), address)

    def _init(self, data: bytes, address, version: int, cookie: bytes):
        port_type, index, use_game_port = data[12], data[13], data[14]
        # The ack echoes the INIT (header, port type, index and local address) with its type changed.
        self.transport.sendto(data[:7] + bytes([INIT_ACK]) + data[8:21], address)
        if index > 1:
            return
        session = self.sessions.get(cookie)
        if session is None:
            session = self.sessions[cookie] = Session(cookie, version)
        client = session.clients.setdefault(index, Client())
        client.addresses[port_type] = address
        client.use_game_port = bool(use_game_port)
        if len(session.clients) == 2 and not session.both_since:
            session.both_since = time.monotonic()
            asyncio.get_running_loop().call_later(SETTLE_SECONDS, self._connect, session)
        if not session.connecting and len(session.clients) == 2 and all(c.ready() for c in session.clients.values()):
            self._connect(session)

    def _connect(self, session: Session, attempt: int = 0):
        if self.sessions.get(session.cookie) is not session or len(session.clients) < 2:
            return
        if session.connecting and attempt == 0:
            return
        session.connecting = True
        a, b = session.clients[0], session.clients[1]
        if attempt == 0:
            log.info("natneg %s: %s:%d <-> %s:%d", session.cookie.hex(), *a.public(), *b.public())
            names = [" & ".join(self.nicks_at(c.public()[0])) or "someone" for c in (a, b)]
            if names[0] != names[1]:        # the same names: players on one network, nothing to say
                notify.post(f"🔗 {names[0]} and {names[1]} connected for co-op", *names,
                            *self.nicks_at(a.public()[0]), *self.nicks_at(b.public()[0]))
        for me, other in ((a, b), (b, a)):
            if me.acked:
                continue
            ip, port = other.public()
            packet = MAGIC + bytes([session.version, CONNECT]) + session.cookie + socket.inet_aton(ip) + \
                struct.pack(">H", port) + b"\x42\x00"
            self.transport.sendto(packet, me.reply_to())
        if attempt < 4 and not (a.acked and b.acked):
            asyncio.get_running_loop().call_later(RESEND_SECONDS, self._connect, session, attempt + 1)

    async def _expire(self):
        while True:
            await asyncio.sleep(20)
            now = time.monotonic()
            for cookie, session in list(self.sessions.items()):
                if now - session.started > SESSION_SECONDS:
                    del self.sessions[cookie]
