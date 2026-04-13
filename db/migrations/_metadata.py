"""Shared SQLAlchemy MetaData instance with a standard naming convention.

Import this in env.py so autogenerate has a stable naming convention from day one,
and in ORM model files once models are defined.

Naming convention tokens:
  %(constraint_name)s  -- explicit name (passthrough)
  %(referred_table_name)s / %(column_0_name)s / %(table_name)s -- used in templates
"""

from __future__ import annotations

import sqlalchemy as sa

# Standard naming convention that Alembic autogenerate will use when it emits
# ADD CONSTRAINT / CREATE INDEX DDL.  Keeps generated names deterministic.
_naming_convention: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

metadata = sa.MetaData(naming_convention=_naming_convention)
