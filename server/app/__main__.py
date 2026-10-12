"""Run the aggregator with uvicorn."""

import uvicorn

from .settings import Settings


def main() -> None:
    """Start the HTTP server on the configured host and port."""
    settings = Settings.from_env()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
