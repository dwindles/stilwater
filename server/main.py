"""Stilwater Online: the GameSpy services Saints Row 2 uses for online co-op, in one process.

    python3 main.py [--bind 0.0.0.0] [--data /var/lib/stilwater-online] [--keys /etc/stilwater-online]

Ports: TCP 29900 (accounts and friends), TCP 29901 (player search), UDP 27900 (availability and
host registration), TCP 28910 (game list), UDP 27901 (NAT negotiation), and HTTP on 127.0.0.1:29980
(AuthService and Sake, behind nginx on port 80). The core points the game's GameSpy hostnames here
([Stilwater] OnlineServer in juiced.ini)."""
import argparse
import asyncio
import logging
import os

from accounts import Accounts
from master import Master
from natneg import NatNeg
from presence import Presence
from webservices import WebServices


async def run(bind: str, data: str, keys: str, web_bind: str):
    os.makedirs(data, exist_ok=True)
    accounts = Accounts(os.path.join(data, "accounts.db"))
    presence = Presence(accounts)
    servers = [
        await asyncio.start_server(presence.serve_client, bind, 29900),
        await asyncio.start_server(presence.serve_search, bind, 29901),
        await Master().start(bind),
        await WebServices(presence, accounts, data, keys).start(web_bind),
    ]
    await NatNeg().start(bind)
    logging.info("Stilwater Online listening on %s", bind)
    await asyncio.gather(*(s.serve_forever() for s in servers))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    parser.add_argument("--keys", default="/etc/stilwater-online", help="folder with authservice.pem and peerkey.pem")
    parser.add_argument("--web-bind", default="127.0.0.1", help="where the HTTP services listen (nginx forwards to them)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    asyncio.run(run(args.bind, args.data, args.keys, args.web_bind))


if __name__ == "__main__":
    main()
