"""Accounts, friends, friend requests and offline messages, in SQLite.

GameSpy splits an account into a user (email and password) and profiles (nicks) under it. We keep
that split because the protocol carries both ids, but give every nick its own user: a nick is
unique here (GameSpy's namespace 1 wasn't), so a friend can be found by nick alone. The password is
stored as its MD5, which is what GameSpy's login hash is built from."""
import re
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL COLLATE NOCASE,
    password_md5 TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    nick TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created INTEGER NOT NULL,
    last_login INTEGER
);
CREATE INDEX IF NOT EXISTS users_email ON users(email);
CREATE TABLE IF NOT EXISTS friends (
    owner INTEGER NOT NULL,
    friend INTEGER NOT NULL,
    PRIMARY KEY (owner, friend)
);
CREATE TABLE IF NOT EXISTS requests (
    sender INTEGER NOT NULL,
    recipient INTEGER NOT NULL,
    reason TEXT NOT NULL,
    sent INTEGER NOT NULL,
    PRIMARY KEY (sender, recipient)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    sender INTEGER NOT NULL,
    recipient INTEGER NOT NULL,
    body TEXT NOT NULL,
    sent INTEGER NOT NULL
);
"""

NICK = re.compile(r"^[A-Za-z0-9_\-\[\]\.]{3,20}$")
EMAIL = re.compile(r"^[^@\s\\]+@[^@\s\\]+\.[^@\s\\]+$")
# Ids look like GameSpy's so nothing in the game treats them as special.
FIRST_USER = 2000000
FIRST_PROFILE = 20000000


class AccountError(Exception):
    def __init__(self, code: int, text: str):
        super().__init__(text)
        self.code = code
        self.text = text


class Accounts:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # --- profiles

    def profile(self, profile_id: int):
        return self.db.execute(
            "SELECT p.id, p.nick, p.user_id, u.email, u.password_md5 FROM profiles p JOIN users u ON u.id = p.user_id "
            "WHERE p.id = ?", (profile_id,)).fetchone()

    def by_nick(self, nick: str):
        return self.db.execute(
            "SELECT p.id, p.nick, p.user_id, u.email, u.password_md5 FROM profiles p JOIN users u ON u.id = p.user_id "
            "WHERE p.nick = ?", (nick,)).fetchone()

    def by_email(self, email: str) -> list:
        return self.db.execute(
            "SELECT p.id, p.nick, p.user_id, u.email, u.password_md5 FROM profiles p JOIN users u ON u.id = p.user_id "
            "WHERE u.email = ? ORDER BY p.id", (email,)).fetchall()

    def create(self, email: str, nick: str, password_md5: str):
        """Creates an account. Errors carry GameSpy's codes (GP_NEWUSER_*)."""
        if not EMAIL.match(email):
            raise AccountError(0x200, "That email address isn't valid.")
        if not NICK.match(nick):
            raise AccountError(0x201, "Nicks are 3-20 letters, digits or _ - [ ] .")
        existing = self.by_nick(nick)
        if existing:
            if existing["email"].lower() == email.lower() and existing["password_md5"] == password_md5:
                return existing           # the game retries; same details, same account
            raise AccountError(0x201, "That nick is taken.")
        now = int(time.time())
        with self.db:
            user_id = self._next_id("users", FIRST_USER)
            self.db.execute("INSERT INTO users (id, email, password_md5, created) VALUES (?, ?, ?, ?)",
                            (user_id, email, password_md5, now))
            profile_id = self._next_id("profiles", FIRST_PROFILE)
            self.db.execute("INSERT INTO profiles (id, user_id, nick, created) VALUES (?, ?, ?, ?)",
                            (profile_id, user_id, nick, now))
        return self.profile(profile_id)

    def touch(self, profile_id: int):
        with self.db:
            self.db.execute("UPDATE profiles SET last_login = ? WHERE id = ?", (int(time.time()), profile_id))

    def _next_id(self, table: str, first: int) -> int:
        return self.db.execute(f"SELECT COALESCE(MAX(id), ?) + 1 FROM {table}", (first,)).fetchone()[0]

    # --- friends (always both ways)

    def friends(self, profile_id: int) -> list[int]:
        return [row[0] for row in self.db.execute("SELECT friend FROM friends WHERE owner = ? ORDER BY friend", (profile_id,))]

    def are_friends(self, a: int, b: int) -> bool:
        return self.db.execute("SELECT 1 FROM friends WHERE owner = ? AND friend = ?", (a, b)).fetchone() is not None

    def befriend(self, a: int, b: int):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO friends VALUES (?, ?)", (a, b))
            self.db.execute("INSERT OR IGNORE INTO friends VALUES (?, ?)", (b, a))
            self.db.execute("DELETE FROM requests WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)",
                            (a, b, b, a))

    def unfriend(self, a: int, b: int):
        with self.db:
            self.db.execute("DELETE FROM friends WHERE (owner = ? AND friend = ?) OR (owner = ? AND friend = ?)", (a, b, b, a))

    def request(self, sender: int, recipient: int, reason: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO requests VALUES (?, ?, ?, ?)", (sender, recipient, reason, int(time.time())))

    def has_request(self, sender: int, recipient: int) -> bool:
        return self.db.execute("SELECT 1 FROM requests WHERE sender = ? AND recipient = ?", (sender, recipient)).fetchone() is not None

    def requests_for(self, recipient: int) -> list:
        return self.db.execute("SELECT sender, reason FROM requests WHERE recipient = ? ORDER BY sent", (recipient,)).fetchall()

    # --- messages kept for players who were offline

    def store_message(self, sender: int, recipient: int, body: str):
        with self.db:
            self.db.execute("INSERT INTO messages (sender, recipient, body, sent) VALUES (?, ?, ?, ?)",
                            (sender, recipient, body, int(time.time())))

    def take_messages(self, recipient: int) -> list:
        with self.db:
            rows = self.db.execute("SELECT sender, body, sent FROM messages WHERE recipient = ? ORDER BY id", (recipient,)).fetchall()
            self.db.execute("DELETE FROM messages WHERE recipient = ?", (recipient,))
        return rows
