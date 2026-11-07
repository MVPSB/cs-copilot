"""工号密码：pbkdf2 哈希 + HMAC 签名令牌（不引入第三方依赖）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from .config import config

ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def issue_token(agent_id: str, ttl_seconds: int = 12 * 3600) -> str:
    expires = int(time.time()) + ttl_seconds
    payload = f"{agent_id}:{expires}"
    sig = hmac.new(config.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def read_token(token: str) -> str | None:
    try:
        payload = base64.urlsafe_b64decode(token.encode()).decode()
        agent_id, expires, sig = payload.rsplit(":", 2)
    except Exception:
        return None
    if int(expires) < time.time():
        return None
    expected = hmac.new(config.secret.encode(), f"{agent_id}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]
    return agent_id if hmac.compare_digest(sig, expected) else None
