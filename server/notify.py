"""Posts a compact feed of what happens on Stilwater Online (players coming online, new accounts,
friendships, invites, co-op games) to a Discord webhook. The webhook comes from
STILWATER_DISCORD_WEBHOOK, which the service reads from /etc/stilwater-online/discord.env; without
it nothing is posted.

To keep the channel readable, events are gathered for BATCH_SECONDS and sent as one message,
the same line twice shows once, and presence and games are debounced: a player is
online from their first session until they've had none for OFFLINE_GRACE seconds (so the launcher
handing over to the game, which signs out and in again, doesn't show), and a game that closes and
is hosted again from the same address within REHOST_GRACE seconds counts as one game. Test
accounts and hosts (server/test_online.py) are never posted."""
import asyncio
import json
import logging
import os
import re
import time
import urllib.request

log = logging.getLogger("notify")
WEBHOOK = os.environ.get("STILWATER_DISCORD_WEBHOOK", "").strip()
if WEBHOOK and not WEBHOOK.startswith("https://"):
    log.warning("STILWATER_DISCORD_WEBHOOK isn't a webhook URL (%r); not posting to Discord", WEBHOOK[:40])
    WEBHOOK = ""
# Discord allows about 30 webhook messages a minute; batching keeps the channel and the limit happy.
BATCH_SECONDS = 20
OFFLINE_GRACE = 180
REHOST_GRACE = 60
TEST_NAME = re.compile(r"^test[a-z]?_[0-9a-f]{6}$|^test host ", re.I)

_pending: list[str] = []
_flushing = False
_online: dict[str, float] = {}                  # nick -> when they came online
_going: dict[str, asyncio.TimerHandle] = {}     # nick -> pending "went offline"
_games: dict[str, tuple[str, tuple, float]] = {}  # host address -> (name, every name involved, started)
_ending: dict[str, asyncio.TimerHandle] = {}    # host address -> pending "game ended"


def post(text: str, *names: str):
    """Queues one line. Lines about test accounts (any of names) are dropped."""
    if not WEBHOOK or any(TEST_NAME.match(n or "") for n in names):
        return
    global _flushing
    _pending.append(text.replace("@", "@​"))
    if not _flushing:
        _flushing = True
        asyncio.get_running_loop().call_later(BATCH_SECONDS, _flush)


def signed_in(nick: str):
    """A session (launcher or game) started for nick."""
    timer = _going.pop(nick, None)
    if timer:
        timer.cancel()          # back within the grace period: still the same visit
    elif nick not in _online:
        _online[nick] = time.monotonic()
        post(f"🟢 **{nick}** is online", nick)


def signed_out(nick: str):
    """nick's session ended; they count as offline if they don't come back soon."""
    if nick in _online and nick not in _going:
        _going[nick] = asyncio.get_running_loop().call_later(OFFLINE_GRACE, _went_offline, nick)


def _went_offline(nick: str):
    _going.pop(nick, None)
    since = _online.pop(nick, None)
    if since is not None:
        post(f"⚫ {nick} went offline after {_duration(time.monotonic() - since - OFFLINE_GRACE)}", nick)


def game_hosted(address: str, name: str, *names: str):
    """A game was hosted from address; name is how to call the host, names everyone it could be
    (for leaving tests out)."""
    timer = _ending.pop(address, None)
    if timer:
        timer.cancel()          # re-hosted straight away: the same game carries on
    elif address not in _games:
        _games[address] = (name, names, time.monotonic())
        post(f"🎮 **{name}** is hosting a co-op game", name, *names)


def game_closed(address: str):
    if address in _games and address not in _ending:
        _ending[address] = asyncio.get_running_loop().call_later(REHOST_GRACE, _game_ended, address)


def _game_ended(address: str):
    _ending.pop(address, None)
    name, names, started = _games.pop(address, ("?", (), time.monotonic()))
    post(f"🎮 {name}'s co-op game ended after {_duration(time.monotonic() - started - REHOST_GRACE)}", name, *names)


def _duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


def _flush():
    global _flushing
    lines, _pending[:] = _pending[:], []
    _flushing = False
    message = ""
    for line in dict.fromkeys(lines):       # the same event twice (the launcher and the game both invite) shows once
        if len(message) + len(line) > 1900:
            asyncio.get_running_loop().run_in_executor(None, _send, message)
            message = ""
        message += line + "\n"
    if message:
        asyncio.get_running_loop().run_in_executor(None, _send, message)


def _send(text: str):
    body = json.dumps({"content": text, "username": "Stilwater Online", "allowed_mentions": {"parse": []}}).encode()
    try:
        request = urllib.request.Request(WEBHOOK, body, {"Content-Type": "application/json",
                                                         "User-Agent": "StilwaterOnline (holdonquietly.com, 1.0)"})
        urllib.request.urlopen(request, timeout=10).read()
    except Exception as e:      # a log line must never take the server down
        log.warning("Discord webhook failed: %s", e)
