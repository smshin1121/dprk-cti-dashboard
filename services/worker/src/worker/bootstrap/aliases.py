"""Alias-dictionary loader and bijection lint.

The YAML at ``data/dictionaries/aliases.yml`` maps entity **type** →
**canonical name** → list of known aliases. The bootstrap pipeline uses
``AliasDictionary.normalize(type_, name)`` to resolve any vendor variant
to a single canonical before upserting into ``groups`` / ``codenames`` /
``malware`` / ``campaigns``.

Invariants enforced at load time:
  1. Per-type bijection — an alias may appear under at most one canonical
     within a single type. A conflict raises ``AliasDictionaryError``.
  2. No self-reference — a canonical name must not appear in its own
     alias list (redundant, obscures intent).
  3. Non-empty strings — both canonicals and aliases must be non-empty
     after stripping surrounding whitespace.

Lookups are case-insensitive but preserve the canonical's original
casing on the way out. An unknown name returns ``None`` so callers can
decide whether to pass the raw value through or reject the row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml


__all__ = [
    "AliasDictionary",
    "AliasDictionaryError",
    "load_aliases",
]


class AliasDictionaryError(ValueError):
    """Raised when the YAML alias dictionary violates a load-time invariant."""


@dataclass(frozen=True)
class AliasDictionary:
    """Immutable alias map keyed by ``(type, lowercased_name)``.

    The public surface is intentionally small: :meth:`normalize` for
    lookups, :meth:`types` for introspection, and :meth:`canonicals` to
    enumerate canonical names of a given type.
    """

    # Internal storage:
    #   _by_type[type_][lower_name] -> canonical (original casing)
    # Canonicals themselves are also present under their lowercased key
    # so ``normalize("Lazarus", "groups")`` returns "Lazarus" too.
    _by_type: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def types(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_type.keys()))

    def canonicals(self, type_: str) -> tuple[str, ...]:
        """Return every canonical registered under ``type_``, sorted."""
        values = set(self._by_type.get(type_, {}).values())
        return tuple(sorted(values))

    def normalize(self, type_: str, name: str) -> str | None:
        """Return the canonical form of ``name`` under ``type_``, or ``None``.

        Lookup is case-insensitive. Whitespace around ``name`` is stripped
        before the lookup so callers do not need to pre-clean vendor data.
        """
        if not name:
            return None
        table = self._by_type.get(type_)
        if not table:
            return None
        return table.get(name.strip().lower())


def _validate_type_mapping(
    type_: str,
    raw: Mapping[str, list[str] | None],
) -> dict[str, str]:
    """Expand one type's canonical→aliases mapping into a flat index.

    Enforces the three load-time invariants documented at module top and
    raises :class:`AliasDictionaryError` with a precise message on any
    violation.
    """
    flat: dict[str, str] = {}
    # Track where each alias came from so conflict messages can point at
    # the exact pair of canonicals that disagree.
    first_seen: dict[str, str] = {}

    for canonical, aliases in raw.items():
        if not isinstance(canonical, str) or not canonical.strip():
            raise AliasDictionaryError(
                f"{type_}: canonical name must be a non-empty string, got {canonical!r}"
            )
        canonical_clean = canonical.strip()
        canonical_key = canonical_clean.lower()

        # Canonicals self-register so ``normalize("groups", "Lazarus")``
        # returns "Lazarus".
        if canonical_key in flat and flat[canonical_key] != canonical_clean:
            raise AliasDictionaryError(
                f"{type_}: canonical {canonical_clean!r} collides with another "
                f"canonical {flat[canonical_key]!r} at the lowercased-key level"
            )
        flat[canonical_key] = canonical_clean
        first_seen.setdefault(canonical_key, canonical_clean)

        if aliases is None:
            continue
        if not isinstance(aliases, list):
            raise AliasDictionaryError(
                f"{type_}: alias list for {canonical_clean!r} must be a list, "
                f"got {type(aliases).__name__}"
            )

        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise AliasDictionaryError(
                    f"{type_}: alias under {canonical_clean!r} must be a non-empty "
                    f"string, got {alias!r}"
                )
            alias_clean = alias.strip()
            alias_key = alias_clean.lower()

            if alias_key == canonical_key:
                raise AliasDictionaryError(
                    f"{type_}: canonical {canonical_clean!r} lists itself as an "
                    f"alias — drop the redundant entry"
                )

            if alias_key in flat:
                owner = first_seen[alias_key]
                if owner != canonical_clean:
                    raise AliasDictionaryError(
                        f"{type_}: alias {alias_clean!r} is claimed by both "
                        f"{owner!r} and {canonical_clean!r}; bijection violated"
                    )
                # Same canonical listing the alias twice — tolerate silently.
                continue

            flat[alias_key] = canonical_clean
            first_seen[alias_key] = canonical_clean

    return flat


def load_aliases(path: Path | str) -> AliasDictionary:
    """Load and validate the alias dictionary at ``path``.

    Raises :class:`AliasDictionaryError` on any invariant violation.
    Empty type sections (``cve: {}``) are tolerated to keep the schema
    stable without forcing placeholder entries.
    """
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise AliasDictionaryError(
            f"{source}: top-level YAML must be a mapping of type -> canonicals"
        )

    by_type: dict[str, dict[str, str]] = {}
    for type_, canonicals in raw.items():
        if canonicals is None or canonicals == {}:
            by_type[type_] = {}
            continue
        if not isinstance(canonicals, dict):
            raise AliasDictionaryError(
                f"{source}: section {type_!r} must be a mapping, got "
                f"{type(canonicals).__name__}"
            )
        by_type[type_] = _validate_type_mapping(type_, canonicals)

    return AliasDictionary(_by_type=by_type)
