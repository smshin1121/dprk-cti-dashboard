"""Referential integrity expectations (D8 / T11).

Two expectations backed by :class:`worker.bootstrap.aliases.AliasDictionary`:

  - **Forward check** (``groups.canonical_name.forward_check``) —
    ``error`` when any value in the DB's distinct ``groups.name``
    column is absent from the ``groups`` type canonical set in
    ``aliases.yml``. This catches normalize leaks and stale
    dictionary entries.
  - **Reverse check** (``groups.canonical_name.reverse_check``) —
    always caps at ``warn``: emits ``warn`` when YAML has canonicals
    that the DB has never materialised (unused dictionary entries),
    emits ``pass`` when both sets match. Never produces ``error``.

D8 locks ``aliases.yml`` as the single source of truth: when the
two sets drift, YAML wins and the DB is the target of re-
normalization. The forward check is the enforcement point; the
reverse check is advisory only, surfacing unused entries that
might be candidates for cleanup.

Both expectations are **factory-built** with an :class:`AliasDictionary`
instance so the caller (CLI) can inject the same dictionary the
bootstrap pipeline normalized against. Tests can inject a hand-
crafted :class:`AliasDictionary` via :func:`AliasDictionary` directly
or via :func:`worker.bootstrap.aliases.load_aliases` against a
temp-path YAML.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import AliasDictionary
from worker.bootstrap.tables import groups_table
from worker.data_quality.results import Expectation, ExpectationResult


__all__ = [
    "GROUPS_TYPE",
    "build_groups_canonical_forward_check",
    "build_groups_canonical_reverse_check",
]


#: The alias dictionary section name for DPRK group canonicals.
#: Matches the ``groups:`` top-level key in ``aliases.yml``.
GROUPS_TYPE: str = "groups"


async def _fetch_db_group_canonicals(
    session: AsyncSession,
) -> set[str]:
    """Return the distinct ``groups.name`` values currently in the DB."""
    result = await session.execute(sa.select(groups_table.c.name).distinct())
    return {row[0] for row in result if row[0] is not None}


def _yaml_group_canonicals(aliases: AliasDictionary) -> set[str]:
    """Return the canonical names of every entry in the ``groups``
    section of ``aliases.yml``."""
    return set(aliases.canonicals(GROUPS_TYPE))


# ---------------------------------------------------------------------------
# D8 forward check
# ---------------------------------------------------------------------------


def build_groups_canonical_forward_check(
    aliases: AliasDictionary,
) -> Expectation:
    """Factory: returns the forward-check expectation bound to ``aliases``.

    Closes over ``aliases`` so the expectation can be passed through
    :func:`worker.data_quality.runner.run_expectations` without
    re-reading the YAML file. The CLI builds ``aliases`` once at
    entry and hands the same instance to both forward and reverse
    factories, matching D8's "single source of truth" rule.
    """

    async def _check(session: AsyncSession) -> ExpectationResult:
        db_set = await _fetch_db_group_canonicals(session)
        yaml_set = _yaml_group_canonicals(aliases)
        missing = db_set - yaml_set

        return ExpectationResult(
            name="groups.canonical_name.forward_check",
            severity="error" if missing else "pass",
            observed_rows=len(missing),
            threshold=0,
            detail={
                "source_of_truth": "aliases.yml",
                "db_canonical_count": len(db_set),
                "yaml_canonical_count": len(yaml_set),
                "offending_db_canonicals": sorted(missing),
            } if missing else {
                "source_of_truth": "aliases.yml",
                "db_canonical_count": len(db_set),
                "yaml_canonical_count": len(yaml_set),
            },
        )

    return Expectation(
        name="groups.canonical_name.forward_check",
        check=_check,
    )


# ---------------------------------------------------------------------------
# D8 reverse check
# ---------------------------------------------------------------------------


def build_groups_canonical_reverse_check(
    aliases: AliasDictionary,
) -> Expectation:
    """Factory: returns the reverse-check expectation bound to ``aliases``.

    Reverse check is advisory only — it never produces ``error``.
    An empty unused-set is ``pass``; a non-empty set is ``warn``.
    This matches D8's "reverse violation is benign" rule: a YAML
    canonical never materialised in the DB might just be an actor
    the corpus has not yet observed, or a dictionary entry added
    ahead of incoming data.
    """

    async def _check(session: AsyncSession) -> ExpectationResult:
        db_set = await _fetch_db_group_canonicals(session)
        yaml_set = _yaml_group_canonicals(aliases)
        unused = yaml_set - db_set

        return ExpectationResult(
            name="groups.canonical_name.reverse_check",
            severity="warn" if unused else "pass",
            observed_rows=len(unused),
            detail={
                "source_of_truth": "aliases.yml",
                "db_canonical_count": len(db_set),
                "yaml_canonical_count": len(yaml_set),
                "unused_yaml_canonicals": sorted(unused),
            },
        )

    return Expectation(
        name="groups.canonical_name.reverse_check",
        check=_check,
    )
