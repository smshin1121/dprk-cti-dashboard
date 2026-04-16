"""Prefect flow wrapper for the RSS ingest runner.

Per D3, this is @flow decoration only — no deployment, no schedule,
no worker infrastructure.
"""

from __future__ import annotations

from prefect import flow, get_run_logger


@flow(name="rss-ingest")
def rss_ingest_flow() -> None:
    logger = get_run_logger()
    logger.info("RSS ingest flow invoked — use CLI for actual execution")
