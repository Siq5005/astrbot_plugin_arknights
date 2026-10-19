"""Run the aggregator with uvicorn."""

import logging

import uvicorn

from .settings import Settings


def main() -> None:
    """Start the HTTP server on the configured host and port."""
    settings = Settings.from_env()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        log_config=None,
    )


if __name__ == "__main__":
    main()
