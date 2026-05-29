from __future__ import annotations

import hashlib
import time
import urllib.parse
from collections.abc import Mapping

_QUERY_SAFE_CHARS = "@"


def encode_query(params: Mapping[str, object]) -> str:
    """Encode params exactly the way the API expects when computing the signature.

    Key detail: ``@`` must NOT be percent-encoded — the upstream signing implementation
    treats it as a safe character, and a mismatch breaks the SHA1 digest.
    """
    return urllib.parse.urlencode(params, doseq=False, safe=_QUERY_SAFE_CHARS)


def sign_public(salt: int, password_hash: str, params: Mapping[str, object]) -> str:
    """Signature for the unauthenticated ``authSource`` call (login)."""
    qs = encode_query(params)
    return hashlib.sha1(f"{salt}{password_hash}&{qs}".encode()).hexdigest()


def sign_authenticated(salt: int, secret: str, token: str, params: Mapping[str, object]) -> str:
    """Signature for any post-login API call."""
    qs = encode_query(params)
    return hashlib.sha1(f"{salt}{secret}{token}&{qs}".encode()).hexdigest()


def now_salt() -> int:
    """Salt is the current Unix epoch in seconds — a fresh value per request."""
    return int(time.time())


def build_public_payload(password_hash: str, params: Mapping[str, object]) -> dict[str, object]:
    salt = now_salt()
    return {
        "sign": sign_public(salt, password_hash, params),
        "salt": salt,
        **params,
    }


def build_authenticated_payload(
    token: str, secret: str, params: Mapping[str, object]
) -> dict[str, object]:
    salt = now_salt()
    return {
        "sign": sign_authenticated(salt, secret, token, params),
        "salt": salt,
        "token": token,
        **params,
    }
