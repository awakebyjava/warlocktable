"""Users, PINs and sessions (plan doc 4.8). Step 3 of seven.

Two files beside the config, both small, both written the way config is
(atomic, validated, previous version kept):

    users.json      id, name, email, role, pin (scrypt), created, lockout
    sessions.json   token HASH -> user id, mode, issued, last seen

WHAT THIS IS, AND IS NOT

The threat model is "don't mix Jon's campaign up with Sarah's" and "a
player must not fire scenes" -- on a LAN that is already the perimeter.
So: PINs, not passwords. scrypt so a copied users.json is not a list of
PINs; a deliberate ~1 s on a wrong PIN and a 30 s lockout after five, so
a phone cannot walk 10,000 codes in a minute. No HTTPS, no email sending,
no reset flow: the admin resets a PIN from the panel, or from the Pi with
`run_service.py --reset-admin-pin` if it is the admin's own.

"GM" IS NOT A ROLE. A session carries a MODE -- "gm" or "player" -- chosen
at login. The same account is a player on Tuesday and the GM on Friday.
The roles are `admin` (the table's owner; the shared library is theirs)
and `user` (everyone else, with a private library). A guest has no
account, no session and can only be a player.

Sessions are a 32-byte random token in an HttpOnly, SameSite=Lax cookie,
thirty days sliding. The file stores the token's SHA-256, so a copied
sessions.json logs nobody in. They survive a service restart on purpose:
5.3's auto-recovery must never sign the GM out mid-game.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import ConfigError, write_json_atomic

ADMIN, USER = "admin", "user"
GM, PLAYER = "gm", "player"
ROLES = (ADMIN, USER)
MODES = (GM, PLAYER)

PIN_MIN, PIN_MAX = 4, 6
MAX_FAILURES = 5
LOCKOUT_S = 30.0
WRONG_PIN_DELAY_S = 1.0
SESSION_TTL_S = 30 * 24 * 3600.0
COOKIE = "wt_session"

# scrypt parameters. n=2**14 is ~50-100 ms on a Pi 4 -- enough to make a
# guess cost something, not enough to make a right PIN feel slow.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


class AuthError(Exception):
    """A refusal the caller should show the person: wrong PIN, locked."""


def hash_pin(pin: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P,
                                     salt.hex(), digest.hex())


def check_pin(pin: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(pin.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and PIN_MIN <= len(pin) <= PIN_MAX


def new_id() -> str:
    return "u_" + secrets.token_hex(4)


@dataclass
class User:
    id: str
    name: str
    email: str
    role: str = USER
    pin_hash: Optional[str] = None
    created: float = field(default_factory=time.time)
    failed: int = 0
    locked_until: Optional[float] = None

    @property
    def has_pin(self) -> bool:
        return bool(self.pin_hash)

    def public(self) -> dict:
        """What a login screen may know: never the hash or the counters."""
        return {"id": self.id, "name": self.name, "role": self.role,
                "needs_pin": not self.has_pin}


class UserStore:
    """users.json. One writer, one lock, atomic file."""

    def __init__(self, path: Optional[str], log=None):
        self.path = path
        self.log = log
        self._lock = threading.RLock()
        self.users: Dict[str, User] = {}
        self._load()

    # ---- persistence

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as exc:
            # 4.8 failure modes: a broken users file is not a hardware
            # fault. Start with no users -- which means the set-up page --
            # and say so. The table keeps running either way.
            if self.log:
                self.log.record("users.unreadable", path=self.path, error=str(exc))
            return
        for u in raw.get("users") or []:
            try:
                user = User(**{k: u.get(k) for k in User.__dataclass_fields__ if k in u})
            except TypeError:
                continue
            self.users[user.id] = user

    def _save(self) -> None:
        if not self.path:
            return
        payload = {"users": [asdict(u) for u in self.users.values()]}
        write_json_atomic(self.path, payload, None, "users")

    # ---- queries

    def needs_setup(self) -> bool:
        """No admin yet, or the admin has no PIN: the set-up page owns the
        panel until this is false."""
        admin = self.admin()
        return admin is None or not admin.has_pin

    def admin(self) -> Optional[User]:
        for u in self.users.values():
            if u.role == ADMIN:
                return u
        return None

    def get(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

    def by_email(self, email: str) -> Optional[User]:
        email = (email or "").strip().lower()
        for u in self.users.values():
            if u.email == email:
                return u
        return None

    def listing(self) -> List[dict]:
        """For the profile picker: names, nothing secret."""
        return [u.public() for u in sorted(self.users.values(),
                                           key=lambda u: (u.role != ADMIN, u.name.lower()))]

    # ---- writes

    def create(self, name: str, email: str, role: str = USER,
               pin: Optional[str] = None) -> User:
        name = (name or "").strip()
        email = (email or "").strip().lower()
        if not name:
            raise ConfigError("a name is required")
        if not email or "@" not in email:
            raise ConfigError("an email address is required")
        if role not in ROLES:
            raise ConfigError("role must be admin or user")
        if pin is not None and not valid_pin(pin):
            raise ConfigError("a PIN is %d to %d digits" % (PIN_MIN, PIN_MAX))
        with self._lock:
            if self.by_email(email) is not None:
                raise ConfigError("that email already has an account")
            if role == ADMIN and self.admin() is not None:
                raise ConfigError("there is already an admin")
            user = User(id=new_id(), name=name, email=email, role=role,
                        pin_hash=hash_pin(pin) if pin else None)
            self.users[user.id] = user
            self._save()
        if self.log:
            self.log.record("users.created", user=user.id, name=name, role=role)
        return user

    def set_pin(self, user_id: str, pin: str) -> None:
        if not valid_pin(pin):
            raise ConfigError("a PIN is %d to %d digits" % (PIN_MIN, PIN_MAX))
        with self._lock:
            user = self.users[user_id]
            user.pin_hash = hash_pin(pin)
            user.failed, user.locked_until = 0, None
            self._save()
        if self.log:
            self.log.record("users.pin_set", user=user_id)

    def clear_pin(self, user_id: str) -> None:
        """The reset: the person sets a new PIN at their next login."""
        with self._lock:
            user = self.users[user_id]
            user.pin_hash = None
            user.failed, user.locked_until = 0, None
            self._save()
        if self.log:
            self.log.record("users.pin_cleared", user=user_id)

    def update(self, user_id: str, name: Optional[str] = None,
               email: Optional[str] = None, role: Optional[str] = None) -> User:
        with self._lock:
            user = self.users[user_id]
            if name is not None:
                name = name.strip()
                if not name:
                    raise ConfigError("a name is required")
                user.name = name
            if email is not None:
                email = email.strip().lower()
                other = self.by_email(email)
                if other is not None and other.id != user_id:
                    raise ConfigError("that email already has an account")
                if not email or "@" not in email:
                    raise ConfigError("an email address is required")
                user.email = email
            if role is not None:
                if role not in ROLES:
                    raise ConfigError("role must be admin or user")
                if role != ADMIN and user.role == ADMIN:
                    raise ConfigError("the admin cannot be demoted; make someone else admin first")
                if role == ADMIN and self.admin() is not None and self.admin().id != user_id:
                    raise ConfigError("there is already an admin")
                user.role = role
            self._save()
        return user

    def delete(self, user_id: str) -> User:
        with self._lock:
            user = self.users[user_id]
            if user.role == ADMIN:
                raise ConfigError("the admin account cannot be deleted")
            del self.users[user_id]
            self._save()
        if self.log:
            self.log.record("users.deleted", user=user_id)
        return user

    # ---- the check

    def verify(self, user_id: str, pin: str, now: Optional[float] = None) -> User:
        """The PIN check, with lockout. Raises AuthError with a message fit
        to show; a wrong PIN also costs WRONG_PIN_DELAY_S of the caller's
        time (the caller sleeps, so tests need not)."""
        now = time.time() if now is None else now
        with self._lock:
            user = self.users.get(user_id)
            if user is None:
                raise AuthError("no such account")
            if not user.has_pin:
                raise AuthError("this account has no PIN yet")
            if user.locked_until and now < user.locked_until:
                raise AuthError("locked for %d s after too many wrong PINs"
                                % int(user.locked_until - now + 0.999))
            if check_pin(pin or "", user.pin_hash):
                user.failed, user.locked_until = 0, None
                self._save()
                return user
            user.failed += 1
            if user.failed >= MAX_FAILURES:
                user.locked_until = now + LOCKOUT_S
                user.failed = 0
            self._save()
        if self.log:
            self.log.record("users.wrong_pin", user=user_id)
        raise AuthError("wrong PIN")


@dataclass
class Session:
    user_id: str
    mode: str
    issued: float
    seen: float

    def expired(self, now: float) -> bool:
        return now - self.seen > SESSION_TTL_S


class SessionStore:
    """sessions.json, keyed by the SHA-256 of the token."""

    def __init__(self, path: Optional[str], log=None):
        self.path = path
        self.log = log
        self._lock = threading.RLock()
        self.sessions: Dict[str, Session] = {}
        self._load()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return
        now = time.time()
        for key, s in (raw.get("sessions") or {}).items():
            try:
                sess = Session(user_id=s["user_id"], mode=s.get("mode", PLAYER),
                               issued=float(s["issued"]), seen=float(s["seen"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not sess.expired(now):
                self.sessions[key] = sess

    def _save(self) -> None:
        if not self.path:
            return
        payload = {"sessions": {k: asdict(s) for k, s in self.sessions.items()}}
        write_json_atomic(self.path, payload, None, "sessions")

    def issue(self, user_id: str, mode: str) -> str:
        if mode not in MODES:
            raise ConfigError("mode must be gm or player")
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self.sessions[self._key(token)] = Session(user_id, mode, now, now)
            self._save()
        return token

    def lookup(self, token: Optional[str], now: Optional[float] = None) -> Optional[Session]:
        """The live session for a token, sliding its expiry. None if absent
        or expired."""
        if not token:
            return None
        now = time.time() if now is None else now
        key = self._key(token)
        with self._lock:
            sess = self.sessions.get(key)
            if sess is None:
                return None
            if sess.expired(now):
                del self.sessions[key]
                self._save()
                return None
            # Slide, but do not rewrite the file on every request: once an
            # hour is plenty to keep a thirty-day window honest.
            if now - sess.seen > 3600:
                sess.seen = now
                self._save()
            return sess

    def set_mode(self, token: str, mode: str) -> None:
        if mode not in MODES:
            raise ConfigError("mode must be gm or player")
        with self._lock:
            sess = self.sessions.get(self._key(token))
            if sess is not None:
                sess.mode = mode
                self._save()

    def revoke(self, token: Optional[str]) -> None:
        if not token:
            return
        with self._lock:
            if self.sessions.pop(self._key(token), None) is not None:
                self._save()

    def revoke_user(self, user_id: str) -> int:
        with self._lock:
            dead = [k for k, s in self.sessions.items() if s.user_id == user_id]
            for k in dead:
                del self.sessions[k]
            if dead:
                self._save()
        return len(dead)


# ------------------------------------------------------------ cookies

def cookie_value(header: Optional[str], name: str = COOKIE) -> Optional[str]:
    """The value of one cookie from a Cookie: header, or None."""
    if not header:
        return None
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v or None
    return None


def set_cookie_header(token: str) -> str:
    # No Secure flag: the panel is plain HTTP on the LAN and the flag would
    # make the cookie vanish (4.8).
    return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (
        COOKIE, token, int(SESSION_TTL_S))


def clear_cookie_header() -> str:
    return "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % COOKIE


class Auth:
    """The pair, plus the dev seeding, as one object the server holds."""

    DEV_PIN = "0000"

    def __init__(self, data_dir: Optional[str], log=None, dev: bool = False):
        users_path = os.path.join(data_dir, "users.json") if data_dir else None
        sessions_path = os.path.join(data_dir, "sessions.json") if data_dir else None
        self.users = UserStore(users_path, log)
        self.sessions = SessionStore(sessions_path, log)
        self.dev = dev
        if dev and not self.users.users:
            # The laptop's fakes-only loop must not be slowed by a login.
            # In memory only: path is None on the dev store, so nothing
            # is written and nothing like this can reach a real install.
            self.users.path = None
            self.sessions.path = None
            self.users.create("dev", "dev@example.invalid", ADMIN, self.DEV_PIN)
            if log:
                log.record("users.dev_admin", pin=self.DEV_PIN)

    def resolve(self, cookie_header: Optional[str]) -> Tuple[Optional[User], Optional[Session], Optional[str]]:
        """(user, session, token) for a request, or (None, None, None)."""
        token = cookie_value(cookie_header)
        sess = self.sessions.lookup(token)
        if sess is None:
            return None, None, None
        user = self.users.get(sess.user_id)
        if user is None:
            self.sessions.revoke(token)
            return None, None, None
        return user, sess, token
