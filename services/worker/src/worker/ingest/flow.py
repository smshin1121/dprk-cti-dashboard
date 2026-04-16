"""Prefect flow wrapper for the RSS ingest runner.

Per D3, this is @flow decoration only — no deployment, no schedule,
no worker infrastructure. The canonical execution path is the CLI:
``python -m worker.ingest run --database-url ...``.

This flow exists so that ``worker.main.rss_ingest`` has a valid
Prefect flow target. When Prefect deployment infrastructure lands
(future PR), this flow will be extended to accept parameters and
call ``run_rss_ingest`` directly.
"""

from __future__ import annotations

from prefect import flow, get_run_logger


@flow(name="rss-ingest")
def rss_ingest_flow() -> None:
    logger = get_run_logger()
    logger.info(
        "RSS ingest flow stub — use 'python -m worker.ingest run "
        "--database-url ...' for actual execution (D3: no Prefect "
        "deployment in PR #8)"
    )
