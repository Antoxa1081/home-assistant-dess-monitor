"""Unit tests for ``sdk.models`` — credential/identity dataclasses."""
from __future__ import annotations

import hashlib

import pytest

from custom_components.dess_monitor.sdk import models


class TestCredentials:
    def test_from_password_hashes_with_sha1(self) -> None:
        creds = models.Credentials.from_password("alice", "hunter2")
        assert creds.username == "alice"
        assert creds.password_hash == hashlib.sha1(b"hunter2").hexdigest()

    def test_never_stores_plaintext(self) -> None:
        creds = models.Credentials.from_password("alice", "hunter2")
        assert "hunter2" not in (creds.username, creds.password_hash)

    def test_frozen(self) -> None:
        creds = models.Credentials("alice", "abc")
        with pytest.raises(Exception):
            creds.username = "bob"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = models.Credentials.from_password("u", "p")
        b = models.Credentials.from_password("u", "p")
        assert a == b


class TestDeviceIdentity:
    def test_as_params_stringifies_everything(self) -> None:
        ident = models.DeviceIdentity(devaddr=1, devcode=2376, pn="PN1", sn="SN1")
        assert ident.as_params() == {
            "devaddr": "1",
            "devcode": "2376",
            "pn": "PN1",
            "sn": "SN1",
        }

    def test_from_dict(self) -> None:
        ident = models.DeviceIdentity.from_dict(
            {"devaddr": "1", "devcode": "2", "pn": "p", "sn": "s", "extra": "ignored"}
        )
        assert ident.devaddr == "1"
        assert ident.devcode == "2"
        assert ident.pn == "p"
        assert ident.sn == "s"

    def test_from_dict_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            models.DeviceIdentity.from_dict({"devaddr": "1"})

    def test_roundtrip_from_dict_as_params(self) -> None:
        src = {"devaddr": "5", "devcode": "9", "pn": "PN", "sn": "SN"}
        ident = models.DeviceIdentity.from_dict(src)
        assert ident.as_params() == src

    def test_frozen(self) -> None:
        ident = models.DeviceIdentity(1, 2, "p", "s")
        with pytest.raises(Exception):
            ident.pn = "other"  # type: ignore[misc]


class TestAuth:
    def test_fields(self) -> None:
        auth = models.Auth(
            token="t", secret="s", expire=3600, uid="u", usr="alice", issued_at=1700000000
        )
        assert auth.token == "t"
        assert auth.secret == "s"
        assert auth.expire == 3600
        assert auth.issued_at == 1700000000
