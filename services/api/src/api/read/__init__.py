"""Read surface package for PR #11 Phase 2.2.

Contains cross-endpoint helpers reused by /reports and /incidents
(``pagination``) and per-endpoint query/repository modules added by
Groups B–E. Imports from this package are deliberately lazy — the
router modules pull in only what they need so the package layout
does not create coupling between read endpoints that plan D3 /
D9 explicitly keep separate (actors offset, dashboard aggregate,
no detail endpoints).
"""
