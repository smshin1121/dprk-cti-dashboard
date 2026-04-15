"""Constants owned by the data-quality gate (PR #7 Group D, T15a).

This module is the landing spot for any code-level constant the DQ
suite needs that does not already live in an authoritative location
elsewhere in the worker. PR #7 introduces exactly one such constant:

  :data:`TLP_VALUES` — the conventional 4-member TLP (Traffic Light
  Protocol) set used by the bootstrap schema's ``reports.tlp``
  column. The value was previously hard-coded only as a Postgres
  ``server_default`` string in migration 0001 and a lower-case
  repetition in the design document; no Python code declared the
  full set. D11 / V1 makes this the authoritative reference so the
  ``reports.tlp.value_domain`` expectation and any future consumer
  (API enum, frontend filter, LLM prompt guardrail) can import a
  single source of truth.

If the DQ suite grows and needs more constants, keep them here. If
a constant is useful to non-DQ code it belongs in whichever module
owns that feature — the rule of thumb is "a DQ constant is one the
DQ gate is the primary consumer of".
"""

from __future__ import annotations


__all__ = ["TLP_VALUES"]


#: Conventional 4-member TLP set.
#:
#: Treats the values as an ordered escalation (WHITE < GREEN < AMBER
#: < RED) only for documentation; :mod:`worker.data_quality`
#: expectations do not depend on the ordering, only on set
#: membership. Matches the design doc v2.0 §9 TLP policy and the
#: ``reports.tlp`` column's ``server_default='WHITE'`` declared in
#: migration 0001.
TLP_VALUES: frozenset[str] = frozenset({"WHITE", "GREEN", "AMBER", "RED"})
