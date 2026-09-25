import argparse
import logging

import uvicorn

from src.configuration.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the synthetic Azure SQL POC API using environment configuration."
    )
    parser.parse_args()
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(name)s %(message)s"
    )
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
