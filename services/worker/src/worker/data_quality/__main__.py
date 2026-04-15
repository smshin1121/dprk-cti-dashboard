"""Module entry point for ``python -m worker.data_quality``.

Delegates to :func:`worker.data_quality.cli.main` so the command-
line layer lives in a single file while the module hook is
trivially testable.
"""

from __future__ import annotations

from worker.data_quality.cli import main


if __name__ == "__main__":  # pragma: no cover — module entry path
    raise SystemExit(main())
