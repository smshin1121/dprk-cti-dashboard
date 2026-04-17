"""Keyset cursor codec for /reports and /incidents.

Plan §2.1 D3 locks keyset pagination for the two list endpoints
whose underlying rows arrive out-of-order under concurrent writes
(reports.published / incidents.reported — both ``DATE`` columns,
see db/migrations/versions/0001_initial_schema.py lines 82, 135).
D11 locks the sort direction to DESC on the date column with id
DESC as the tiebreaker. The cursor therefore carries exactly
``(sort_date, last_id)``.

Design notes (review checklist — plan §8 review priorities):

1. **Opaque.** The wire format is urlsafe-base64 of
   ``f"{date.isoformat()}|{row_id}"``. Clients never introspect
   the payload; the server is free to switch the inner encoding
   later (e.g. to a signed payload) and any cursor a stale client
   replays surfaces as HTTP 422 through ``CursorDecodeError``
   rather than silently falling back to page 1.
2. **Uniform 422 on invalid.** Plan D12 locks "invalid filter
   values never silently ignored". Routers catch
   ``CursorDecodeError`` and return 422 — distinct from the PR #10
   staging endpoint which used a 400. The two read endpoints in
   PR #11 adopt the uniform 422 contract.
3. **Actors NOT wired here.** D3 keeps actors on offset
   pagination (small row count, sort-stable). Forcing actors
   through this helper would either require a dummy sort value or
   fork the signature — Group B's actors route builds offset
   params inline instead. This module intentionally exposes only
   primitives useful to date-cursor consumers.
4. **Date-only.** Both reports and incidents sort on a ``DATE``
   column. ``date.fromisoformat`` rejects full datetime strings,
   so a cursor forged with a datetime payload fails to decode
   rather than silently truncating — the date-only contract is
   enforced at the boundary. If a future list endpoint ever sorts
   on a ``TIMESTAMP`` column, add a new helper; do not widen this
   one (date vs datetime ambiguity is a footgun under round-trip).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date


class CursorDecodeError(ValueError):
    """Raised by ``decode_cursor`` on malformed input.

    The read-endpoint routers catch this and return HTTP 422 with
    a ``{"error": "malformed_cursor", ...}`` body that matches the
    rest of the endpoint's invalid-filter contract (plan D12).
    """


@dataclass(frozen=True)
class DecodedCursor:
    """Parsed cursor payload.

    ``sort_value`` is a ``date`` (reports.published / incidents.reported).
    ``last_id`` is the row id of the last item on the previous page;
    callers use it as the tiebreaker in the WHERE clause under the
    ``(sort_value, id)`` DESC ordering lock.
    """

    sort_value: date
    last_id: int


def encode_cursor(sort_value: date, last_id: int) -> str:
    """Encode ``(sort_value, last_id)`` as an opaque base64 string.

    Stripping the ``=`` padding shortens the wire form; the decoder
    re-pads before ``b64decode``. ``last_id < 0`` is a caller bug —
    raise ``ValueError`` rather than silently encoding nonsense.
    """
    if last_id < 0:
        raise ValueError("last_id must be non-negative")
    raw = f"{sort_value.isoformat()}|{last_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> DecodedCursor:
    """Decode an opaque cursor into ``DecodedCursor(sort_value, last_id)``.

    Every failure mode collapses to ``CursorDecodeError`` so the
    router has exactly one exception to map to 422. Empty strings,
    bad base64, wrong separator, non-integer id, non-date value,
    negative id — all raise the same error.
    """
    if not cursor:
        raise CursorDecodeError("cursor cannot be empty")

    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise CursorDecodeError(f"cursor is not valid base64: {exc}") from None

    if "|" not in raw:
        raise CursorDecodeError("cursor missing separator")

    value_str, id_str = raw.rsplit("|", 1)

    try:
        sort_value = date.fromisoformat(value_str)
    except ValueError as exc:
        raise CursorDecodeError(f"cursor sort_value is not ISO-format date: {exc}") from None

    try:
        last_id = int(id_str)
    except ValueError as exc:
        raise CursorDecodeError(f"cursor last_id is not an integer: {exc}") from None

    if last_id < 0:
        raise CursorDecodeError("cursor last_id is negative")

    return DecodedCursor(sort_value=sort_value, last_id=last_id)


__all__ = [
    "CursorDecodeError",
    "DecodedCursor",
    "decode_cursor",
    "encode_cursor",
]
