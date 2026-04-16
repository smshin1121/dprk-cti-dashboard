"""Prefect flow wrapper for the TAXII ingest pipeline.

Per decision D3: ``@flow`` decoration + local CLI entrypoint only.
No Prefect deployment, schedule, or worker infrastructure.
The flow is callable as a Python function (for tests) and via CLI
(for operators). Later wrapping with ``prefect deploy`` is additive.

P2 Codex R1: the flow calls the async run logic directly instead of
``cli.main()`` to avoid ``sys.exit()`` killing the Prefect process.
"""

from __future__ import annotations

from prefect import flow


__all__ = ["taxii_ingest_flow"]


@flow(name="taxii-ingest")
async def taxii_ingest_flow() -> None:
    """Thin Prefect flow wrapper for TAXII ingest.

    The actual logic lives in ``worker.ingest.taxii.runner.run_taxii_ingest``.
    This flow exists solely to satisfy §14 W4 "Prefect 플로우" wording
    at zero infrastructure cost. The CLI is the canonical entrypoint.

    Calls the async run command directly to avoid ``sys.exit()``.
    """
    from worker.ingest.taxii.cli import _run_command_for_flow
    await _run_command_for_flow()
