"""`python -m cohortex_agent`: serve the API with uvicorn on 0.0.0.0:8000."""

from __future__ import annotations

import logging
import os

import uvicorn

from cohortex_agent.app import create_app
from cohortex_agent.config import Settings


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    settings = Settings.from_env()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(create_app(settings), host="0.0.0.0", port=port, log_level="info")  # noqa: S104


if __name__ == "__main__":
    main()
