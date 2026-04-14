from prefect import flow, get_run_logger

from .telemetry import setup_telemetry

setup_telemetry()


@flow(name="bootstrap-etl")
def bootstrap_etl() -> None:
    logger = get_run_logger()
    logger.info("Bootstrap ETL scaffold ready")


@flow(name="rss-taxii-ingest")
def ingest_sources() -> None:
    logger = get_run_logger()
    logger.info("RSS/TAXII ingest scaffold ready")


@flow(name="llm-enrich")
def llm_enrich() -> None:
    logger = get_run_logger()
    logger.info("LLM enrichment scaffold ready")


@flow(name="anomaly-alerts")
def anomaly_alerts() -> None:
    logger = get_run_logger()
    logger.info("Anomaly and alert scaffold ready")


def run() -> None:
    bootstrap_etl()
    ingest_sources()
    llm_enrich()
    anomaly_alerts()


if __name__ == "__main__":
    run()
