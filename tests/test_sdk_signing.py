"""Unit tests for ``sdk.signing`` — the API request signature builders.

The signature scheme is SHA1 over a very specific concatenation; the exact
byte layout (including the unescaped ``@``) is what the upstream cloud expects,
so these tests pin the format rather than re-deriving it.
"""
from __future__ import annotations

import hashlib

import pytest

from custom_components.dess_monitor.sdk import signing


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class TestEncodeQuery:
    def test_basic_pairs(self) -> None:
        assert signing.encode_query({"a": "1", "b": "2"}) == "a=1&b=2"

    def test_at_sign_is_not_escaped(self) -> None:
        # The upstream signer treats '@' as safe; escaping it breaks the digest.
        assert signing.encode_query({"action": "auth@source"}) == "action=auth@source"

    def test_other_specials_are_escaped(self) -> None:
        assert signing.encode_query({"x": "a b/c"}) == "x=a+b%2Fc"

    def test_preserves_insertion_order(self) -> None:
        params = {"z": "1", "a": "2", "m": "3"}
        assert signing.encode_query(params) == "z=1&a=2&m=3"

    def test_empty(self) -> None:
        assert signing.encode_query({}) == ""


class TestSignPublic:
    def test_matches_manual_sha1(self) -> None:
        params = {"action": "authSource", "usr": "bob"}
        salt = 1700000000
        pwd = "deadbeef"
        qs = signing.encode_query(params)
        expected = _sha1(f"{salt}{pwd}&{qs}")
        assert signing.sign_public(salt, pwd, params) == expected

    def test_changes_with_salt(self) -> None:
        params = {"action": "authSource"}
        a = signing.sign_public(1, "h", params)
        b = signing.sign_public(2, "h", params)
        assert a != b

    def test_is_hex_sha1_length(self) -> None:
        sig = signing.sign_public(1, "h", {"a": "1"})
        assert len(sig) == 40
        int(sig, 16)  # raises if not hex


class TestSignAuthenticated:
    def test_matches_manual_sha1(self) -> None:
        params = {"action": "webQueryDeviceEs", "page": "0"}
        salt, secret, token = 1700000000, "s3cr3t", "tok123"
        qs = signing.encode_query(params)
        expected = _sha1(f"{salt}{secret}{token}&{qs}")
        assert signing.sign_authenticated(salt, secret, token, params) == expected

    def test_differs_from_public_scheme(self) -> None:
        # The public scheme hashes salt+pwdhash; the authenticated scheme hashes
        # salt+secret+token. Pick inputs whose concatenations can't collide.
        params = {"action": "x"}
        pub = signing.sign_public(1, "PWDHASH", params)
        auth = signing.sign_authenticated(1, "SECRET", "TOKEN", params)
        assert pub != auth


class TestNowSalt:
    def test_returns_int_epoch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(signing.time, "time", lambda: 1700000000.9)
        assert signing.now_salt() == 1700000000


class TestBuildPayloads:
    def test_public_payload_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(signing, "now_salt", lambda: 42)
        payload = signing.build_public_payload("pwdhash", {"action": "authSource"})
        assert payload["salt"] == 42
        assert payload["action"] == "authSource"
        assert payload["sign"] == signing.sign_public(42, "pwdhash", {"action": "authSource"})

    def test_authenticated_payload_includes_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(signing, "now_salt", lambda: 7)
        payload = signing.build_authenticated_payload("tok", "sec", {"action": "x"})
        assert payload["token"] == "tok"
        assert payload["salt"] == 7
        assert payload["sign"] == signing.sign_authenticated(7, "sec", "tok", {"action": "x"})

    def test_user_params_take_precedence_over_reserved_keys(self) -> None:
        # ``**params`` is spread last in build_*, so a caller-supplied key wins.
        # Pin this so a refactor that reorders the spread is caught.
        payload = signing.build_public_payload("h", {"sign": "USERVALUE"})
        assert payload["sign"] == "USERVALUE"
