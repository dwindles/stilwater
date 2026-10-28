"""GameSpy Presence: the account server (gpcm, TCP 29900) that the game and the launcher stay
signed in to, and the search server (gpsp, TCP 29901) that looks players up.

Messages are \\key\\value pairs ending in \\final\\. Buddy messages (\\bm\\) carry a type: 1 text
(the launcher's invites ride on these), 2 friend request, 4 request accepted, 6 removed,
100 status, 101 game invite."""
import asyncio
import base64
import binascii
import logging
import secrets
import socket
import struct
import time

import gamespy as gs
import notify
from accounts import Accounts, AccountError

log = logging.getLogger("presence")

MAX_MESSAGE = 128 * 1024      # a profile picture is up to 64 KB, sent as base64
KEEPALIVE_SECONDS = 60
IDLE_SECONDS = 300

# GameSpy error codes (gp.h).
GP_PARSE = 0x0001
GP_NOT_LOGGED_IN = 0x0002
GP_BAD_SESSKEY = 0x0003
GP_FORCED_DISCONNECT = 0x0006
GP_LOGIN_BAD_NICK = 0x0102
GP_LOGIN_BAD_EMAIL = 0x0103
GP_LOGIN_BAD_PASSWORD = 0x0104
GP_LOGIN_BAD_PROFILE = 0x0105
GP_NEWUSER_BAD_NICK = 0x0201
GP_NEWUSER_BAD_PASSWORD = 0x0202
GP_ADDBUDDY_BAD_NEW = 0x0602
GP_ADDBUDDY_ALREADY_BUDDY = 0x0603
GP_GETPROFILE_BAD_PROFILE = 0x0A01
GP_CHECK_BAD_EMAIL = 0x0E01
GP_CHECK_BAD_NICK = 0x0E02
GP_CHECK_BAD_PASSWORD = 0x0E03

BM_MESSAGE, BM_REQUEST, BM_AUTH, BM_REVOKE, BM_STATUS, BM_INVITE = 1, 2, 4, 6, 100, 101


async def read_messages(reader: asyncio.StreamReader):
    """Yields complete messages from a stream (several can arrive in one packet)."""
    buffer = b""
    while True:
        end = buffer.find(b"\\final\\")
        if end >= 0:
            text, buffer = buffer[:end + 7], buffer[end + 7:]
            yield text.decode("latin-1")
            continue
        if len(buffer) > MAX_MESSAGE:
            return
        chunk = await asyncio.wait_for(reader.read(4096), IDLE_SECONDS)
        if not chunk:
            return
        buffer += chunk


def signature(*parts) -> str:
    return gs.md5("|".join(str(p) for p in parts) + secrets.token_hex(4))


class Session:
    def __init__(self, server: "Presence", writer: asyncio.StreamWriter):
        self.server = server
        self.writer = writer
        self.address = writer.get_extra_info("peername") or ("0.0.0.0", 0)
        self.challenge = gs.challenge()
        self.session_key = 0
        self.profile_id = 0
        self.nick = ""
        self.status = 0
        self.status_text = ""
        self.location = ""
        self.port = 0
        self.closed = False
        self.launcher = False       # the Stilwater launcher, not the game: it takes the sw* extensions
        self.ticket = ""

    def send(self, *pairs):
        if self.closed:
            return
        try:
            self.writer.write(gs.message(*pairs))
        except (ConnectionError, RuntimeError):
            self.closed = True

    def error(self, code: int, text: str, fatal: bool = False, request_id: str = "1"):
        pairs = [("error", ""), ("err", code)]
        if fatal:
            pairs.append(("fatal", ""))
        pairs += [("errmsg", text), ("id", request_id)]
        self.send(*pairs)

    def close(self):
        if not self.closed:
            self.closed = True
            self.writer.close()

    def status_message(self) -> tuple:
        """This player's status as a buddy status message body."""
        ip = struct.unpack("<i", socket.inet_aton(self.address[0]))[0] if self.status else 0
        text = f"|s|{self.status}|ss|{self.status_text}|ls|{self.location}|ip|{ip}|p|{self.port if self.status else 0}|qm|0"
        return ("bm", BM_STATUS), ("f", self.profile_id), ("msg", text)


class Presence:
    def __init__(self, accounts: Accounts):
        self.accounts = accounts
        # Each player can be signed in twice at once: in the game and in the launcher (which says so
        # with \swlauncher\1 in its login). profile id -> {is launcher: session}.
        self.sessions: dict[int, dict[bool, Session]] = {}
        # Login tickets (\lt\ in the login reply) -> profile id; Sake and shared mods requests carry them.
        self.tickets: dict[str, int] = {}
        self.master = None          # set by main.py: an accepted invite pins the joiner's game list

    @property
    def online(self) -> dict[int, "Session"]:
        """Who is signed in, by the session friends see: the game's when it's running."""
        return {pid: self.primary(pid) for pid in self.sessions}

    def primary(self, profile_id: int):
        both = self.sessions.get(profile_id, {})
        return both.get(False) or both.get(True)

    def deliver(self, profile_id: int, *pairs, launcher_only: bool = False):
        """Sends a message to every session of a player (or only their launcher's)."""
        for is_launcher, session in self.sessions.get(profile_id, {}).items():
            if is_launcher or not launcher_only:
                session.send(*pairs)

    # --- gpcm

    async def serve_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        session = Session(self, writer)
        session.send(("lc", 1), ("challenge", session.challenge), ("id", 1))
        keepalive = asyncio.create_task(self._keepalive(session))
        try:
            async for text in read_messages(reader):
                command, fields = gs.parse(text)
                handler = getattr(self, "cmd_" + command, None)
                if handler is None:
                    log.debug("gpcm %s: unhandled %s", session.address[0], command)
                    continue
                if command not in ("login", "newuser", "ka") and not session.profile_id:
                    session.error(GP_NOT_LOGGED_IN, "You're not signed in.", True, fields.get("id", "1"))
                    break
                handler(session, fields)
                await writer.drain()
                if session.closed:
                    break
        except (asyncio.TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            keepalive.cancel()
            self._signed_out(session)
            session.close()

    async def _keepalive(self, session: Session):
        while not session.closed:
            await asyncio.sleep(KEEPALIVE_SECONDS)
            session.send(("ka", ""))

    def _signed_out(self, session: Session):
        both = self.sessions.get(session.profile_id, {})
        if session.profile_id and both.get(session.launcher) is session:
            del both[session.launcher]
            self.tickets.pop(session.ticket, None)
            log.info("%s signed out of the %s", session.nick, "launcher" if session.launcher else "game")
            if both:
                self._tell_friends(self.primary(session.profile_id))     # still in the other one
                return
            del self.sessions[session.profile_id]
            session.status, session.status_text, session.location = 0, "Offline", ""
            self._tell_friends(session)
            notify.signed_out(session.nick)

    def nicks_at(self, ip: str) -> list[str]:
        """Who is signed in from this address (to name hosts and players in the Discord feed)."""
        return [s.nick for s in self.online.values() if s.address[0] == ip]

    def _tell_friends(self, session: Session):
        """Tells session's friends its status, if it's the session they see."""
        if session.status and self.primary(session.profile_id) is not session:
            return
        for friend in self.accounts.friends(session.profile_id):
            self.deliver(friend, *session.status_message())

    def cmd_ka(self, session: Session, fields):
        pass

    def cmd_login(self, session: Session, fields):
        request_id = fields.get("id", "1")
        if "user" in fields:
            user = fields["user"]
            nick, _, email = user.partition("@")
            profile = self.accounts.by_nick(nick)
            if profile is None:
                return session.error(GP_LOGIN_BAD_NICK if self.accounts.by_email(email) else GP_LOGIN_BAD_EMAIL,
                                     "There's no account with that nick and email.", True, request_id)
            if profile["email"].lower() != email.lower():
                return session.error(GP_LOGIN_BAD_EMAIL, "That email doesn't match this nick.", True, request_id)
        elif "uniquenick" in fields:
            user = fields["uniquenick"]
            profile = self.accounts.by_nick(user)
            if profile is None:
                return session.error(GP_LOGIN_BAD_NICK, "There's no account with that nick.", True, request_id)
        else:
            return session.error(GP_PARSE, "Sign in with a nick and email.", True, request_id)

        partner = fields.get("partnerid", "0")
        hashed_user = user if partner in ("", "0") else f"{partner}@{user}"
        client_challenge = fields.get("challenge", "")
        expected = gs.login_hash(profile["password_md5"], hashed_user, client_challenge, session.challenge)
        if fields.get("response", "").lower() != expected:
            log.info("bad password for %s from %s", profile["nick"], session.address[0])
            return session.error(GP_LOGIN_BAD_PASSWORD, "The password is incorrect.", True, request_id)

        # Signing in again in the same place (game or launcher) replaces that session; the game and
        # the launcher stay signed in side by side.
        session.launcher = session.launcher or fields.get("swlauncher") == "1"
        both = self.sessions.setdefault(profile["id"], {})
        previous = both.get(session.launcher)
        if previous:
            previous.error(GP_FORCED_DISCONNECT, "You signed in somewhere else.", True)
            previous.profile_id = 0
            self.tickets.pop(previous.ticket, None)
            previous.close()
        session.profile_id = profile["id"]
        session.nick = profile["nick"]
        session.session_key = secrets.randbelow(0x7FFFFFFF - 1) + 1
        session.port = int(fields.get("port", "0") or 0)
        session.status, session.status_text = 1, "Online"
        both[session.launcher] = session
        self.accounts.touch(session.profile_id)
        proof = gs.login_hash(profile["password_md5"], hashed_user, session.challenge, client_challenge)
        ticket = secrets.token_urlsafe(16)[:22] + "__"
        session.ticket = ticket
        self.tickets[ticket] = profile["id"]
        session.send(("lc", 2), ("sesskey", session.session_key), ("proof", proof), ("userid", profile["user_id"]),
                     ("profileid", profile["id"]), ("uniquenick", profile["nick"]), ("lt", ticket), ("id", request_id))
        log.info("%s signed in from %s", session.nick, session.address[0])
        notify.signed_in(session.nick)

        friends = self.accounts.friends(session.profile_id)
        session.send(("bdy", len(friends)), ("list", ",".join(map(str, friends))))
        for friend in friends:
            other = self.online.get(friend)
            if other:
                session.send(*other.status_message())
        for row in self.accounts.requests_for(session.profile_id):
            session.send(("bm", BM_REQUEST), ("f", row["sender"]),
                         ("msg", f"{row['reason']}|signed|{signature(row['sender'], session.profile_id)}"))
        for row in self.accounts.take_messages(session.profile_id):
            session.send(("bm", BM_MESSAGE), ("f", row["sender"]), ("date", row["sent"]), ("msg", row["body"]))
        self._tell_friends(session)

    def cmd_newuser(self, session: Session, fields):
        request_id = fields.get("id", "1")
        try:
            profile = self._new_user(fields)
        except AccountError as e:
            return session.error(e.code, e.text, False, request_id)
        session.send(("nur", ""), ("userid", profile["user_id"]), ("profileid", profile["id"]), ("id", request_id))

    def _new_user(self, fields):
        password = fields.get("password")
        if password is None:
            encoded = fields.get("passwordenc", fields.get("passenc", ""))
            try:
                password = gs.decode_password(encoded)
            except (ValueError, UnicodeError):
                raise AccountError(GP_NEWUSER_BAD_PASSWORD, "The password couldn't be read.")
        if len(password) < 4:
            raise AccountError(GP_NEWUSER_BAD_PASSWORD, "Passwords need at least 4 characters.")
        nick = fields.get("uniquenick") or fields.get("nick", "")
        profile = self.accounts.create(fields.get("email", ""), nick, gs.md5(password))
        log.info("new account %s", profile["nick"])
        notify.post(f"New account: {profile['nick']}", profile["nick"])
        return profile

    def cmd_logout(self, session: Session, fields):
        session.close()

    def cmd_status(self, session: Session, fields):
        try:
            session.status = int(fields.get("status", "1") or 1)
        except ValueError:
            session.status = 1
        session.status_text = fields.get("statstring", "")[:255].replace("|", "")
        session.location = fields.get("locstring", "")[:255].replace("|", "")
        self._tell_friends(session)

    def cmd_getprofile(self, session: Session, fields):
        request_id = fields.get("id", "1")
        try:
            profile = self.accounts.profile(int(fields.get("profileid", "0")))
        except ValueError:
            profile = None
        if profile is None:
            return session.error(GP_GETPROFILE_BAD_PROFILE, "No such player.", False, request_id)
        own = profile["id"] == session.profile_id
        session.send(("pi", ""), ("profileid", profile["id"]), ("nick", profile["nick"]), ("userid", profile["user_id"]),
                     ("email", profile["email"] if own else ""), ("sig", signature(profile["id"])),
                     ("uniquenick", profile["nick"]), ("pid", 0), ("firstname", ""), ("lastname", ""),
                     ("homepage", ""), ("zipcode", ""), ("countrycode", ""), ("st", "  "), ("birthday", 0),
                     ("sex", 2), ("icquin", 0), ("aim", ""), ("pic", 0), ("pmask", 64), ("occ", 0), ("ind", 0),
                     ("inc", 0), ("mar", 0), ("chc", 0), ("i1", 0), ("o1", 0), ("conn", 0), ("id", request_id))

    def cmd_addbuddy(self, session: Session, fields):
        try:
            target = int(fields.get("newprofileid", "0"))
        except ValueError:
            target = 0
        if target == session.profile_id or self.accounts.profile(target) is None:
            return session.error(GP_ADDBUDDY_BAD_NEW, "No such player.", False)
        if self.accounts.are_friends(session.profile_id, target):
            return session.error(GP_ADDBUDDY_ALREADY_BUDDY, "You're already friends.", False)
        if self.accounts.has_request(target, session.profile_id):
            # They asked us first: asking back accepts.
            return self._accept(session, target)
        reason = fields.get("reason", "")[:200].replace("|", "")
        self.accounts.request(session.profile_id, target, reason)
        notify.post(f"{session.nick} sent {self._nick(target)} a friend request", session.nick, self._nick(target))
        self.deliver(target, ("bm", BM_REQUEST), ("f", session.profile_id),
                     ("msg", f"{reason}|signed|{signature(session.profile_id, target)}"))

    def cmd_authadd(self, session: Session, fields):
        try:
            sender = int(fields.get("fromprofileid", "0"))
        except ValueError:
            return
        if self.accounts.has_request(sender, session.profile_id):
            self._accept(session, sender)

    def _nick(self, profile_id: int) -> str:
        profile = self.accounts.profile(profile_id)
        return profile["nick"] if profile else f"#{profile_id}"

    def _accept(self, session: Session, other_id: int):
        self.accounts.befriend(session.profile_id, other_id)
        notify.post(f"{session.nick} and {self._nick(other_id)} are now friends", session.nick, self._nick(other_id))
        other = self.primary(other_id)
        if other:
            self.deliver(other_id, ("bm", BM_AUTH), ("f", session.profile_id),
                         ("msg", f"I have authorized your request to add me to your list|signed|{signature(session.profile_id)}"))
            self.deliver(other_id, *self.primary(session.profile_id).status_message())
            self.deliver(session.profile_id, *other.status_message())
        else:
            session.send(("bm", BM_STATUS), ("f", other_id), ("msg", "|s|0|ss|Offline|ls||ip|0|p|0|qm|0"))

    def cmd_delbuddy(self, session: Session, fields):
        try:
            other_id = int(fields.get("delprofileid", "0"))
        except ValueError:
            return
        self.accounts.unfriend(session.profile_id, other_id)
        notify.post(f"{session.nick} removed {self._nick(other_id)} as a friend", session.nick, self._nick(other_id))
        self.deliver(other_id, ("bm", BM_REVOKE), ("f", session.profile_id), ("msg", "I have revoked you from my list."))

    def cmd_bm(self, session: Session, fields):
        try:
            kind = int(fields.get("bm", "0"))
            target = int(fields.get("t", "0"))
        except ValueError:
            return
        if not self.accounts.are_friends(session.profile_id, target):
            return
        body = fields.get("msg", "")[:1024]
        if kind == BM_MESSAGE and body.startswith("STILWATER_INVITE|"):
            notify.post(f"{session.nick} invited {self._nick(target)} to co-op", session.nick, self._nick(target))
        if target in self.sessions:
            # The launcher's invites are text the game would show as a chat message: launchers only.
            self.deliver(target, ("bm", kind), ("f", session.profile_id), ("msg", body),
                         launcher_only=body.startswith("STILWATER_"))
        elif kind == BM_MESSAGE:
            self.accounts.store_message(session.profile_id, target, body)

    def cmd_pinvite(self, session: Session, fields):
        try:
            target = int(fields.get("profileid", "0"))
        except ValueError:
            return
        if target in self.sessions and self.accounts.are_friends(session.profile_id, target):
            notify.post(f"{session.nick} invited {self._nick(target)} to co-op", session.nick, self._nick(target))
            self.deliver(target, ("bm", BM_INVITE), ("f", session.profile_id),
                         ("msg", f"|p|{fields.get('productid', gs.PRODUCT_ID)}|l|{fields.get('location', '')}"))

    def cmd_updatepro(self, session: Session, fields):
        pass

    def cmd_updateui(self, session: Session, fields):
        pass

    def cmd_inviteto(self, session: Session, fields):
        pass

    # --- Stilwater extensions, only ever sent by the launcher. Replies and pushes use commands the
    # game doesn't know, so they only go to sessions that said \swhello\.

    def cmd_swhello(self, session: Session, fields):
        if session.launcher:
            return
        # A launcher from before \swlauncher said so only after signing in: file it as the launcher.
        both = self.sessions.get(session.profile_id, {})
        session.launcher = True
        if both.get(False) is session:
            del both[False]
            previous = both.get(True)
            if previous:
                previous.error(GP_FORCED_DISCONNECT, "You signed in somewhere else.", True)
                previous.profile_id = 0
                self.tickets.pop(previous.ticket, None)
                previous.close()
            both[True] = session

    def cmd_swjoin(self, session: Session, fields):
        r"""\swjoin\profileid\<host>: the player accepted host's invite. For the next few minutes
        their game's co-op list (matchmaking) shows only host's game, so the game joins it."""
        request_id = fields.get("id", "1")
        try:
            host_id = int(fields.get("profileid", "0"))
        except ValueError:
            host_id = 0
        host = self.sessions.get(host_id, {}).get(False)
        if not self.accounts.are_friends(session.profile_id, host_id):
            return session.error(GP_PARSE, "You can only join friends.", False, request_id)
        if host is None:
            return session.error(GP_PARSE, f"{self._nick(host_id)} isn't in the game.", False, request_id)
        joiner = self.sessions.get(session.profile_id, {})
        for s in joiner.values():
            if self.master:
                self.master.pin(s.address[0], host.address[0])
        log.info("%s is joining %s", session.nick, host.nick)
        notify.post(f"{session.nick} is joining {host.nick}", session.nick, host.nick)
        session.send(("swjoined", ""), ("profileid", host_id), ("id", request_id))

    def cmd_swsetprofile(self, session: Session, fields):
        """\\swsetprofile\\ with bio and/or avatar (base64 JPEG or PNG; empty removes it)."""
        request_id = fields.get("id", "1")
        try:
            avatar = base64.b64decode(fields["avatar"], validate=True) if "avatar" in fields else None
            digest = self.accounts.set_profile(session.profile_id, fields.get("bio"), avatar)
        except (binascii.Error, ValueError):
            return session.error(GP_PARSE, "That picture couldn't be read.", False, request_id)
        except AccountError as e:
            return session.error(GP_PARSE, e.text, False, request_id)
        session.send(("swprofile", ""), ("profileid", session.profile_id), ("hash", digest), ("id", request_id))
        if avatar is not None:
            log.info("%s changed their profile picture", session.nick)
            notify.post(f"{session.nick} updated their profile picture", session.nick)
        for friend in self.accounts.friends(session.profile_id):
            self.deliver(friend, ("swprofilechanged", ""), ("profileid", session.profile_id), ("hash", digest),
                         launcher_only=True)

    def cmd_swgetprofile(self, session: Session, fields):
        """\\swgetprofile\\profileid\\<id>\\have\\<hash>: the picture comes only when it differs from have."""
        request_id = fields.get("id", "1")
        try:
            profile_id = int(fields.get("profileid", "0"))
        except ValueError:
            profile_id = 0
        profile = self.accounts.public_profile(profile_id)
        if profile is None:
            return session.error(GP_GETPROFILE_BAD_PROFILE, "There's no such player.", False, request_id)
        pairs = [("swprofile", ""), ("profileid", profile_id), ("nick", profile["nick"]), ("bio", profile["bio"]),
                 ("since", profile["created"]), ("hash", profile["avatar_hash"])]
        if profile["avatar_hash"] and profile["avatar_hash"] != fields.get("have", ""):
            pairs.append(("avatar", base64.b64encode(profile["avatar"]).decode()))
        session.send(*pairs, ("id", request_id))

    # --- gpsp: one request per connection, answered and closed

    async def serve_search(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            async for text in read_messages(reader):
                command, fields = gs.parse(text)
                reply = self.search(command, fields)
                if reply:
                    writer.write(reply)
                    await writer.drain()
        except (asyncio.TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    def search(self, command: str, fields: dict) -> bytes:
        if command == "search":
            found = []
            nick = fields.get("uniquenick") or fields.get("nick")
            if nick:
                profile = self.accounts.by_nick(nick)
                found = [profile] if profile else []
            elif fields.get("email"):
                found = self.accounts.by_email(fields["email"])
            pairs = []
            for p in found[:20]:
                pairs += [("bsr", p["id"]), ("nick", p["nick"]), ("firstname", ""), ("lastname", ""), ("email", ""),
                          ("uniquenick", p["nick"]), ("namespaceid", gs.NAMESPACE_ID)]
            return gs.message(*pairs, ("bsrdone", ""), ("more", 0))
        if command == "valid":
            return gs.message(("vr", 1 if self.accounts.by_email(fields.get("email", "")) else 0))
        if command in ("nicks", "check"):
            email = fields.get("email", "")
            profiles = self.accounts.by_email(email)
            try:
                password = fields["pass"] if "pass" in fields else gs.decode_password(fields.get("passenc", ""))
            except (ValueError, UnicodeError):
                password = ""
            matching = [p for p in profiles if p["password_md5"] == gs.md5(password)]
            if command == "nicks":
                if not matching:
                    return gs.message(("error", ""), ("err", 551), ("fatal", ""),
                                      ("errmsg", "Unable to get any associated profiles."), ("id", 1))
                pairs = [("nr", 0)]
                for p in matching:
                    pairs += [("nick", p["nick"]), ("uniquenick", p["nick"])]
                return gs.message(*pairs, ("ndone", ""))
            if not profiles:
                return gs.message(("cur", GP_CHECK_BAD_EMAIL))
            nick = fields.get("nick", "")
            profile = next((p for p in matching if p["nick"].lower() == nick.lower()), None)
            if profile is None:
                code = GP_CHECK_BAD_NICK if not any(p["nick"].lower() == nick.lower() for p in profiles) else GP_CHECK_BAD_PASSWORD
                return gs.message(("cur", code))
            return gs.message(("cur", 0), ("pid", profile["id"]))
        if command == "newuser":
            try:
                profile = self._new_user(fields)
            except AccountError as e:
                return gs.message(("nur", e.code))
            return gs.message(("nur", 0), ("pid", profile["id"]))
        if command == "others":
            return gs.message(("others", ""), ("odone", ""))
        if command == "otherslist":
            return gs.message(("otherslist", ""), ("oldone", ""))
        if command == "uniquesearch":
            return gs.message(("us", 0), ("usdone", ""))
        log.debug("gpsp: unhandled %s", command)
        return b""
