# Root conftest.py — serves as pytest rootdir anchor so that
# `python -m uv run --project services/api pytest -q` from the repo root
# delegates to services/api/pytest.ini for configuration.
# This file intentionally contains no fixtures.
collect_ignore_glob = ["apps/*", "contracts/*", "db/*", "infra/*", "envs/*"]
