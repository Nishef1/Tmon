"""Portfolio access keys. The key is shown once, at creation; only its SHA-256 is stored, so a
leaked database does not open anyone's portfolio."""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX = "tp_"


def new_key() -> str:
    return PREFIX + secrets.token_urlsafe(24)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().encode()).hexdigest()


def matches(key: str | None, key_hash: str) -> bool:
    return bool(key) and hmac.compare_digest(hash_key(key or ""), key_hash)


# -- owner sign-in -----------------------------------------------------------------------------
# One password for the owner of the site. Signing in gives a browser an owner token that opens
# every portfolio, so a new browser needs no portfolio keys. Nothing is stored in the database
# (which the PC overwrites on each data sync): the password's scrypt hash and a signing secret sit
# in the server's environment. A token is signed with a key derived from both, so a new password
# ends every token given before it.
OWNER_PREFIX = "to_"
SCRYPT = {"n": 2**15, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt:{salt.hex()}:{dk.hex()}"


def password_ok(password: str, stored: str) -> bool:
    try:
        kind, salt, _ = stored.split(":")
    except ValueError:
        return False
    if kind != "scrypt" or not password:
        return False
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)


def _signing_key(secret: str, password_hash: str) -> bytes:
    return hmac.new(secret.encode(), password_hash.encode(), hashlib.sha256).digest()


def owner_token(secret: str, password_hash: str) -> str:
    nonce = secrets.token_urlsafe(12)
    sig = hmac.new(_signing_key(secret, password_hash), nonce.encode(), hashlib.sha256).hexdigest()
    return f"{OWNER_PREFIX}{nonce}.{sig}"


def owner_token_ok(token: str | None, secret: str, password_hash: str) -> bool:
    if not token or not secret or not password_hash or not token.startswith(OWNER_PREFIX):
        return False
    nonce, _, sig = token[len(OWNER_PREFIX) :].partition(".")
    want = hmac.new(_signing_key(secret, password_hash), nonce.encode(), hashlib.sha256)
    return bool(nonce) and hmac.compare_digest(want.hexdigest(), sig)


def set_password(env_file: str) -> None:
    """Ask for the owner password twice (never echoed) and write its hash and a fresh secret into
    ``env_file``. Restart the API afterwards."""
    import getpass
    from pathlib import Path

    pw = getpass.getpass("owner password (at least 10 characters): ")
    if len(pw) < 10 or pw != getpass.getpass("again: "):
        raise SystemExit("not set: too short or the two did not match")
    path = Path(env_file)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keep = [
        ln for ln in lines if not ln.startswith(("TMON_OWNER_PASSWORD_HASH=", "TMON_OWNER_SECRET="))
    ]
    keep += [
        f"TMON_OWNER_PASSWORD_HASH={hash_password(pw)}",
        f"TMON_OWNER_SECRET={secrets.token_hex(32)}",
    ]
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    print(f"owner password set in {env_file}; restart the API (systemctl restart tmon-api)")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(prog="python -m tmon.portfolio.keys")
    ap.add_argument("command", choices=["set-password"])
    ap.add_argument("--env-file", default="/etc/tmon.env")
    set_password(ap.parse_args().env_file)
