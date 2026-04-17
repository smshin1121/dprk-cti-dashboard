"""API-facing Pydantic schemas (DTOs).

Separated from ``api.auth.schemas`` (auth-only DTOs) so review/promote and
later read-API DTOs don't pollute the auth namespace. Each submodule owns
one bounded contract: ``review`` for PR #10 staging review/promote.
"""
