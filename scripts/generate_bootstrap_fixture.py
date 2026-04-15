"""Regenerate services/worker/tests/fixtures/bootstrap_sample.xlsx.

The fixture is committed to the repo so CI runs stay deterministic, but the
source-of-truth is the YAML next to it. Editing rows in the YAML and
re-running this script is the canonical way to change the fixture.

Usage (from repo root):

    uv run --project services/worker python scripts/generate_bootstrap_fixture.py

The services/worker virtualenv provides openpyxl and pyyaml as runtime
dependencies for the Bootstrap ETL, so no extra `--with` flags are needed.

The script writes to a fixed path, stamps the workbook with a fixed creation
date and creator so re-runs from the same YAML produce byte-equivalent
output (modulo openpyxl version drift), and drops the private metadata
fields prefixed with `_` before writing cells.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import yaml
    from openpyxl import Workbook
except ImportError as exc:
    print(
        "error: this script needs openpyxl and pyyaml installed. "
        "Run it via `python -m uv run --with openpyxl --with pyyaml "
        "python scripts/generate_bootstrap_fixture.py`.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_YAML = REPO_ROOT / "services/worker/tests/fixtures/bootstrap_sample.yaml"
OUTPUT_XLSX = REPO_ROOT / "services/worker/tests/fixtures/bootstrap_sample.xlsx"

# Metadata keys the YAML uses for reviewer annotations. Rows tagged
# ``_tag: failure_case`` exercise the bootstrap CLI's error paths and
# deliberately push the fixture above the D5 5% failure threshold.
# ``strip_failure_cases`` removes them so CI jobs that need a clean
# seed (e.g. the data-quality-tests end-to-end run) can build a happy
# subset from the same single source YAML without maintaining a second
# fixture file.
_TAG_KEY = "_tag"
_FAILURE_CASE_TAG = "failure_case"


# v1.0 workbook column order per sheet. The loader in services/worker uses
# these exact headers, so the generator must not reorder them.
SHEETS: Sequence[tuple[str, str, Sequence[tuple[str, str]]]] = (
    (
        "actors",
        "Actors",
        (
            ("name", "Name"),
            ("named_by", "Named by"),
            ("associated_group", "Associated Group"),
            ("first_seen", "First seen"),
            ("last_seen", "Last seen"),
        ),
    ),
    (
        "reports",
        "Reports",
        (
            ("published", "Published"),
            ("author", "Author"),
            ("title", "Title"),
            ("url", "URL"),
            ("tags", "Tags"),
        ),
    ),
    (
        "incidents",
        "Incidents",
        (
            ("reported", "Reported"),
            ("victims", "Victims"),
            ("motivations", "Motivations"),
            ("sectors", "Sectors"),
            ("countries", "Countries"),
        ),
    ),
)


def _load_yaml(path: Path) -> Mapping[str, list[Mapping[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return data


def strip_failure_cases(
    source: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Return a new source mapping with ``_tag: failure_case`` rows removed.

    Rows whose ``_tag`` is not ``failure_case`` (including rows with no
    ``_tag`` at all) are preserved verbatim. Non-list sheet values are
    passed through untouched so the caller still sees the same shape
    and :func:`build_workbook` can raise the same validation errors.

    The input mapping is never mutated: each sheet's row list is
    replaced with a freshly filtered list.
    """
    filtered: dict[str, list[Mapping[str, Any]]] = {}
    for sheet_key, rows in source.items():
        if not isinstance(rows, list):
            filtered[sheet_key] = rows  # type: ignore[assignment]
            continue
        filtered[sheet_key] = [
            row
            for row in rows
            if not (
                isinstance(row, dict) and row.get(_TAG_KEY) == _FAILURE_CASE_TAG
            )
        ]
    return filtered


def _cell_value(value: Any) -> Any:
    """Coerce a YAML value into an openpyxl-safe cell value.

    YAML parses ISO dates as `datetime.date`; openpyxl writes them as native
    Excel dates. Empty strings stay empty strings (not None) so the loader
    can distinguish "cell present but blank" from "cell absent".
    """
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value
    return value


def build_workbook(source: Mapping[str, list[Mapping[str, Any]]]) -> Workbook:
    wb = Workbook()
    # openpyxl creates a default sheet named "Sheet"; remove it so the three
    # real sheets are the only sheets present.
    default = wb.active
    wb.remove(default)

    for yaml_key, sheet_title, columns in SHEETS:
        rows = source.get(yaml_key, [])
        if not isinstance(rows, list):
            raise ValueError(
                f"YAML key {yaml_key!r} must be a list, got {type(rows).__name__}"
            )
        ws = wb.create_sheet(title=sheet_title)
        ws.append([header for _, header in columns])
        for index, row in enumerate(rows, start=2):
            if not isinstance(row, dict):
                raise ValueError(
                    f"row {index} under {yaml_key!r} must be a mapping"
                )
            values = [_cell_value(row.get(field)) for field, _ in columns]
            ws.append(values)

    # Deterministic metadata. openpyxl's default would stamp wall-clock time,
    # making every regeneration produce a different binary.
    fixed_stamp = dt.datetime(2026, 4, 15, 0, 0, 0, tzinfo=dt.timezone.utc)
    props = wb.properties
    props.creator = "dprk-cti-bootstrap-fixture-generator"
    props.lastModifiedBy = "dprk-cti-bootstrap-fixture-generator"
    props.created = fixed_stamp
    props.modified = fixed_stamp
    return wb


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regenerate services/worker/tests/fixtures/bootstrap_sample.xlsx from its YAML source.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_XLSX,
        help=(
            "Destination path for the regenerated workbook. Defaults "
            "to the committed fixture location. CI drift checks pass "
            "a temporary path and compare the result against the "
            "committed copy."
        ),
    )
    parser.add_argument(
        "--strip-failure-cases",
        action="store_true",
        help=(
            "Drop every row whose `_tag` metadata is `failure_case` "
            "before writing the workbook. Used by CI jobs that need a "
            "happy-subset seed built from the same source YAML as the "
            "committed stress fixture (e.g. data-quality-tests). The "
            "default behaviour — no flag — regenerates the full stress "
            "fixture and must stay byte-equivalent to the committed "
            "copy for the worker-tests drift check."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output_path = args.output

    if not SOURCE_YAML.exists():
        print(f"error: source YAML not found at {SOURCE_YAML}", file=sys.stderr)
        return 2
    source = _load_yaml(SOURCE_YAML)
    if args.strip_failure_cases:
        source = strip_failure_cases(source)
    wb = build_workbook(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    rows_per_sheet = {key: len(source.get(key, [])) for key, _, _ in SHEETS}
    print(f"wrote {output_path} ({rows_per_sheet})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
