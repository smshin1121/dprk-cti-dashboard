"""Pydantic v2 input row schemas for the v1.0 bootstrap workbook.

Each sheet has its own row model. The loader (T6) is responsible for
mapping spreadsheet column headers to the snake_case field names these
schemas expose.

Validation philosophy:
  - Required fields raise a schema error when missing. The pipeline
    demotes these errors into dead-letter rows.
  - Optional fields stay optional; later normalization stages may still
    flag them.
  - Schemas do **not** resolve alias dictionaries or canonicalize URLs.
    That is the job of ``normalize.py`` and keeps these models pure
    data-shape validators.
  - Schemas do **not** touch the database. Upsert is T6.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


__all__ = [
    "ActorRow",
    "ReportRow",
    "IncidentRow",
    "RowValidationError",
]


# Re-export pydantic's ValidationError under a pipeline-local name so
# callers do not need to import pydantic just to catch it.
from pydantic import ValidationError as RowValidationError  # noqa: E402


# ---------------------------------------------------------------------------
# Country-code validation
# ---------------------------------------------------------------------------
#
# ISO 3166-1 alpha-2 reserves the entire "X*" range (XA..XZ) as
# user-assigned / private-use. Real countries never use these codes, so
# we reject them categorically. This catches the fixture's "XX" failure
# case without pulling in a pycountry dependency for a single check.
_ISO3166_ALPHA2_PATTERN = re.compile(r"^[A-Z]{2}$")
_ISO3166_USER_ASSIGNED_PREFIX = "X"


def _is_valid_iso3166_alpha2(value: str) -> bool:
    if not _ISO3166_ALPHA2_PATTERN.match(value):
        return False
    if value[0] == _ISO3166_USER_ASSIGNED_PREFIX:
        return False
    return True


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _BootstrapRow(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        # Fail on unknown fields so a column drift in the real workbook
        # blows up loud instead of silently dropping data.
        extra="forbid",
        # Pipeline-produced dates may arrive as ``datetime.datetime`` from
        # openpyxl or as ``datetime.date`` from the YAML source; accept
        # both but normalize to ``date``.
        arbitrary_types_allowed=False,
    )


def _coerce_date(value: object) -> dt.date | None:
    """Normalize openpyxl datetimes / YAML dates / strings to ``date``.

    Accepts ``None`` and passes it through so optional date fields can
    distinguish "cell empty" from "cell invalid".
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        return dt.date.fromisoformat(trimmed)
    raise TypeError(f"expected date / datetime / str / None, got {type(value).__name__}")


# ---------------------------------------------------------------------------
# Actor row
# ---------------------------------------------------------------------------


class ActorRow(_BootstrapRow):
    """One row of the Actors sheet.

    ``associated_group`` is the raw vendor value. The alias dictionary
    normalizes it to a canonical group name in a later stage.
    """

    name: Annotated[str, Field(min_length=1)]
    named_by: str | None = None
    associated_group: str | None = None
    first_seen: dt.date | None = None
    last_seen: dt.date | None = None

    @field_validator("first_seen", "last_seen", mode="before")
    @classmethod
    def _coerce_dates(cls, value: object) -> dt.date | None:
        return _coerce_date(value)

    @field_validator("name")
    @classmethod
    def _reject_whitespace_only_name(cls, value: str) -> str:
        if not value:  # already stripped by model_config
            raise ValueError("name must be non-empty")
        return value


# ---------------------------------------------------------------------------
# Report row
# ---------------------------------------------------------------------------

# A very permissive URL check: must start with http:// or https:// and
# contain a host component. The canonicalizer (T4) does the heavy
# lifting; this is just a sanity filter.
_URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


class ReportRow(_BootstrapRow):
    """One row of the Reports sheet."""

    published: dt.date
    author: str | None = None
    title: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(min_length=1)]
    tags: str | None = None

    @field_validator("published", mode="before")
    @classmethod
    def _coerce_published(cls, value: object) -> dt.date | None:
        return _coerce_date(value)

    @field_validator("url")
    @classmethod
    def _validate_url_shape(cls, value: str) -> str:
        if not _URL_PATTERN.match(value):
            raise ValueError(
                f"url must start with http:// or https:// and have a host; got {value!r}"
            )
        return value

    @field_validator("title")
    @classmethod
    def _reject_whitespace_only_title(cls, value: str) -> str:
        if not value:
            raise ValueError("title must be non-empty")
        return value


# ---------------------------------------------------------------------------
# Incident row
# ---------------------------------------------------------------------------


class IncidentRow(_BootstrapRow):
    """One row of the Incidents sheet.

    ``countries`` is a single ISO 3166-1 alpha-2 code in the v1.0
    workbook. The incident mapping table in 0001 lets multiple codes
    attach to a single incident, but the fixture and v1.0 source both
    use a single-country column, so we keep the schema 1:1.
    """

    reported: dt.date
    victims: Annotated[str, Field(min_length=1)]
    motivations: str | None = None
    sectors: str | None = None
    countries: str | None = None

    @field_validator("reported", mode="before")
    @classmethod
    def _coerce_reported(cls, value: object) -> dt.date | None:
        return _coerce_date(value)

    @field_validator("countries")
    @classmethod
    def _validate_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        upper = value.strip().upper()
        if not upper:
            return None
        if not _is_valid_iso3166_alpha2(upper):
            raise ValueError(
                f"countries must be a valid ISO 3166-1 alpha-2 code; got {value!r}"
            )
        return upper
