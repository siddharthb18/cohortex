"""``python -m cohortex_mcp_stats``: streamable HTTP on 0.0.0.0:8102 at /mcp, or ``--stdio``."""

import sys
from collections.abc import Sequence

from cohortex_mcp_common.server import run_cli

from cohortex_mcp_stats.server import DEFAULT_PORT, build_server


def main(argv: Sequence[str] | None = None) -> int:
    """Run the server; returns 2 when the pinned contracts do not match."""
    return run_cli(
        argv,
        factory=build_server,
        default_port=DEFAULT_PORT,
        description="Cohortex mcp-stats: afr_ci, compare_rates, change_point",
    )


if __name__ == "__main__":
    sys.exit(main())
