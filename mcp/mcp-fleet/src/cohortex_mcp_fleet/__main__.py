"""``python -m cohortex_mcp_fleet``: streamable HTTP on 0.0.0.0:8101 at /mcp, or ``--stdio``.

fleet-api is reached at ``$FLEET_API_URL`` (default ``http://localhost:8080``).
"""

import sys
from collections.abc import Sequence

from cohortex_mcp_common.server import run_cli

from cohortex_mcp_fleet.server import DEFAULT_PORT, build_server


def main(argv: Sequence[str] | None = None) -> int:
    """Run the server; returns 2 when the pinned contracts do not match."""
    return run_cli(
        argv,
        factory=build_server,
        default_port=DEFAULT_PORT,
        description="Cohortex mcp-fleet: read-only fleet-api tools",
    )


if __name__ == "__main__":
    sys.exit(main())
