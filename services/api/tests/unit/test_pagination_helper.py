"""Unit tests for ``api.read.pagination`` — keyset cursor codec.

Scope lock from plan §2.1 D3 / D11 / D12 and Group A review
priorities:

- Opaque format: encode/decode round-trip preserves
  ``(sort_value, last_id)`` across any valid date + non-negative id.
- Clients cannot introspect structure: the encoded string is
  urlsafe-base64 (no ``|``, no ``:``, no spaces).
- Every malformed input raises ``CursorDecodeError`` exactly — no
  silent fallback, no type leakage from the underlying exception.
- Date-only contract: a cursor forged with a datetime payload fails
  to decode. If this test regresses, the codec has silently widened
  and reports/incidents could accept cursors that do not round-trip
  to a stable date boundary.
"""

from __future__ import annotations

import base64
from datetime import date, datetime

import pytest

from api.read.pagination import (
    CursorDecodeError,
    DecodedCursor,
    decode_cursor,
    encode_cursor,
)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_basic_date_and_id(self) -> None:
        cursor = encode_cursor(date(2026, 3, 15), 42)
        decoded = decode_cursor(cursor)
        assert decoded == DecodedCursor(sort_value=date(2026, 3, 15), last_id=42)

    def test_epoch_date(self) -> None:
        cursor = encode_cursor(date(1970, 1, 1), 1)
        decoded = decode_cursor(cursor)
        assert decoded.sort_value == date(1970, 1, 1)
        assert decoded.last_id == 1

    def test_far_future_date(self) -> None:
        cursor = encode_cursor(date(2099, 12, 31), 999_999_999)
        decoded = decode_cursor(cursor)
        assert decoded.sort_value == date(2099, 12, 31)
        assert decoded.last_id == 999_999_999

    def test_zero_id(self) -> None:
        cursor = encode_cursor(date(2024, 1, 1), 0)
        assert decode_cursor(cursor).last_id == 0


# ---------------------------------------------------------------------------
# Opaque wire format
# ---------------------------------------------------------------------------


class TestOpaqueFormat:
    def test_encoded_is_urlsafe_base64_without_separator(self) -> None:
        """Clients must not be able to pattern-match the inner
        ``sort|id`` format directly on the wire — the whole point
        of opacity is that the server can evolve the payload."""
        cursor = encode_cursor(date(2026, 3, 15), 42)
        # urlsafe base64 alphabet: A-Z a-z 0-9 - _ (and padding =)
        assert "|" not in cursor
        assert " " not in cursor
        assert ":" not in cursor
        assert all(c.isalnum() or c in "-_" for c in cursor)

    def test_encoded_has_no_padding(self) -> None:
        """Padding trimmed on encode and re-added on decode."""
        cursor = encode_cursor(date(2026, 3, 15), 42)
        assert not cursor.endswith("=")


# ---------------------------------------------------------------------------
# Malformed inputs — all collapse to CursorDecodeError
# ---------------------------------------------------------------------------


class TestMalformedRaises:
    def test_empty_string(self) -> None:
        with pytest.raises(CursorDecodeError, match="empty"):
            decode_cursor("")

    def test_not_base64(self) -> None:
        with pytest.raises(CursorDecodeError):
            decode_cursor("!!!not base64!!!")

    def test_base64_but_no_pipe(self) -> None:
        raw = base64.urlsafe_b64encode(b"no-separator-here").decode("ascii").rstrip("=")
        with pytest.raises(CursorDecodeError, match="separator"):
            decode_cursor(raw)

    def test_bad_date_format(self) -> None:
        raw = base64.urlsafe_b64encode(b"not-a-date|42").decode("ascii").rstrip("=")
        with pytest.raises(CursorDecodeError, match="ISO-format date"):
            decode_cursor(raw)

    def test_datetime_payload_rejected(self) -> None:
        """Date-only contract: a datetime-forged cursor must fail.

        If this regresses, the codec silently widened to accept
        ``T00:00:00`` suffixes and the (date, id) ordering in SQL
        could mis-compare across day boundaries.
        """
        raw = base64.urlsafe_b64encode(b"2026-03-15T12:30:00|42").decode("ascii").rstrip("=")
        with pytest.raises(CursorDecodeError, match="ISO-format date"):
            decode_cursor(raw)

    def test_non_integer_id(self) -> None:
        raw = base64.urlsafe_b64encode(b"2026-03-15|not-int").decode("ascii").rstrip("=")
        with pytest.raises(CursorDecodeError, match="integer"):
            decode_cursor(raw)

    def test_negative_id(self) -> None:
        raw = base64.urlsafe_b64encode(b"2026-03-15|-1").decode("ascii").rstrip("=")
        with pytest.raises(CursorDecodeError, match="negative"):
            decode_cursor(raw)

    def test_non_utf8_payload(self) -> None:
        raw = base64.urlsafe_b64encode(b"\xff\xfe\xfd|1").decode("ascii").rstrip("=")
        with pytest.raises(CursorDecodeError, match="base64"):
            decode_cursor(raw)

    def test_payload_with_extra_separator(self) -> None:
        """Splitting on the rightmost ``|`` means a payload with two
        separators decodes with the LAST segment as the id — valid
        if that segment is an int, invalid otherwise. This test
        pins the "invalid id" branch: the date segment becomes
        ``2026-03-15|extra`` which fails ISO-format parsing."""
        raw = base64.urlsafe_b64encode(b"2026-03-15|extra|42").decode("ascii").rstrip("=")
        with pytest.raises(CursorDecodeError, match="ISO-format date"):
            decode_cursor(raw)


# ---------------------------------------------------------------------------
# Encode-side precondition
# ---------------------------------------------------------------------------


class TestEncodePrecondition:
    def test_rejects_negative_id(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            encode_cursor(date(2026, 3, 15), -1)

    def test_accepts_large_id(self) -> None:
        cursor = encode_cursor(date(2026, 3, 15), 2**40)
        assert decode_cursor(cursor).last_id == 2**40


# ---------------------------------------------------------------------------
# Accidental datetime passthrough guard
# ---------------------------------------------------------------------------


class TestDatetimeGuard:
    def test_datetime_input_still_encodes_as_date_string(self) -> None:
        """``datetime`` subclasses ``date`` — if a caller passes a
        naive datetime by accident, ``.isoformat()`` returns a full
        timestamp and the round-trip decoder must reject it. This
        prevents a silent data corruption where the cursor encodes
        a datetime but the SQL uses a DATE column, producing
        inconsistent page boundaries."""
        dt = datetime(2026, 3, 15, 12, 30)
        cursor = encode_cursor(dt, 42)
        with pytest.raises(CursorDecodeError, match="ISO-format date"):
            decode_cursor(cursor)
