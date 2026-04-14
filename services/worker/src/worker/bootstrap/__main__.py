"""Enable ``python -m worker.bootstrap`` as the Bootstrap ETL entry point."""

from __future__ import annotations

from worker.bootstrap.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
