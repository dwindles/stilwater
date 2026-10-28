"""Posts what happens on Stilwater Online (new accounts, sign-ins, friendships, invites, hosted
games, NAT negotiations) to a Discord webhook. The webhook comes from STILWATER_DISCORD_WEBHOOK,
which the service reads from /etc/stilwater-online/discord.env; without it nothing is posted."""
import asyncio
import json
import logging
import os
import urllib.request

log = logging.getLogger("notify")
WEBHOOK = os.environ.get("STILWATER_DISCORD_WEBHOOK", "").strip()
if WEBHOOK and not WEBHOOK.startswith("https://"):
    log.warning("STILWATER_DISCORD_WEBHOOK isn't a webhook URL (%r); not posting to Discord", WEBHOOK[:40])
    WEBHOOK = ""
# Discord allows about 30 webhook messages a minute; events are batched to stay under that.
BATCH_SECONDS = 3

_pending: list[str] = []
_flushing = False


def post(text: str):
    """Queues one line for the webhook (no-op when none is set)."""
    global _flushing
    if not WEBHOOK:
        return
    _pending.append(text.replace("@", "@​"))
    if not _flushing:
        _flushing = True
        asyncio.get_running_loop().call_later(BATCH_SECONDS, _flush)


def _flush():
    global _flushing
    lines, _pending[:] = _pending[:], []
    _flushing = False
    message = ""
    for line in lines:
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
