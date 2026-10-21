"""Tests for the generic response-parsing helpers."""
from __future__ import annotations

import pytest

from custom_components.dess_monitor.api.protocols.base import Field, ResponseSchema
from custom_components.dess_monitor.api.protocols.enums import OperatingMode
from custom_components.dess_monitor.api.protocols.parsing import (
    decode_token,
    is_nak,
    parse_positional,
    strip_frame,
)


class TestStripFrame:
    def test_empty_input_returned_as_is(self):
        assert strip_frame(b"") == b""

    def test_axpert_paren_header_and_crc_cr(self):
        # '(' header, 2-byte CRC, trailing CR.
        raw = b"(231.8 50.0\xff\xff\r"
        assert strip_frame(raw) == b"231.8 50.0"

    def test_axpert_with_trailing_nul_after_cr(self):
        raw = b"(L\xff\xff\r\x00"
        assert strip_frame(raw) == b"L"

    def test_pi18_header_stripped(self):
        # ^D<len> header is 5 bytes; CRC 2 bytes + CR.
        raw = b"^D005GS\xab\xcd\r"
        assert strip_frame(raw) == b"GS"

    def test_no_cr_still_strips_crc(self):
        # No CR: still removes the trailing 2-byte CRC.
        assert strip_frame(b"AB\xff\xff") == b"AB"

    def test_short_payload_without_crc_room(self):
        # 'A' + CR: CR trimmed leaves 'A' (len 1 < 2 so no CRC strip).
        assert strip_frame(b"A\r") == b"A"

    def test_pi18_header_too_short_not_stripped(self):
        # Starts with ^D but < 5 bytes after CRC/CR handling -> header kept.
        # b"^D\r" -> CR trimmed -> b"^D" -> len 2 -> CRC strip leaves b"".
        assert strip_frame(b"^D\r") == b""


class TestDecodeToken:
    def test_enum_mapping_to_name(self):
        field = Field("operating_mode", enum=OperatingMode)
        assert decode_token(field, "L") == "Line"
        assert decode_token(field, "B") == "Battery"

    def test_enum_unknown_token_passthrough(self):
        field = Field("operating_mode", enum=OperatingMode)
        assert decode_token(field, "Z") == "Z"

    def test_transform_applied(self):
        field = Field("v", transform=lambda t: float(t) / 10)
        assert decode_token(field, "2305") == pytest.approx(230.5)

    def test_plain_token_passthrough(self):
        field = Field("raw")
        assert decode_token(field, "hello") == "hello"

    def test_enum_takes_precedence_over_transform(self):
        # When both are set the enum branch wins (checked first).
        field = Field("m", enum=OperatingMode, transform=lambda t: "TRANSFORMED")
        assert decode_token(field, "L") == "Line"


class TestParsePositional:
    def test_basic_zip(self):
        schema = ResponseSchema("s", (Field("a"), Field("b"), Field("c")))
        assert parse_positional("1 2 3", schema) == {"a": "1", "b": "2", "c": "3"}

    def test_extra_tokens_ignored(self):
        schema = ResponseSchema("s", (Field("a"), Field("b")))
        assert parse_positional("1 2 3 4", schema) == {"a": "1", "b": "2"}

    def test_missing_tokens_omitted(self):
        schema = ResponseSchema("s", (Field("a"), Field("b"), Field("c")))
        assert parse_positional("1 2", schema) == {"a": "1", "b": "2"}

    def test_enum_field_normalised(self):
        schema = ResponseSchema("s", (Field("mode", enum=OperatingMode),))
        assert parse_positional("F", schema) == {"mode": "Fault"}

    def test_multiple_whitespace_split(self):
        schema = ResponseSchema("s", (Field("a"), Field("b")))
        assert parse_positional("1   2", schema) == {"a": "1", "b": "2"}

    def test_empty_payload(self):
        schema = ResponseSchema("s", (Field("a"),))
        assert parse_positional("", schema) == {}


class TestIsNak:
    @pytest.mark.parametrize("payload", ["NAK", "NAK\xff\xff", "(NAK", "foo NAK bar"])
    def test_detects_nak(self, payload):
        assert is_nak(payload) is True

    @pytest.mark.parametrize("payload", ["ACK", "", "nak", "OK"])
    def test_rejects_non_nak(self, payload):
        assert is_nak(payload) is False
