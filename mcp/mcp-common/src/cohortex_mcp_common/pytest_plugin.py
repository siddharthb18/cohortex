"""pytest plugin (auto-loaded via the ``pytest11`` entry point): import the MCP SDK first.

The repository has a top-level ``mcp/`` directory. Under ``--import-mode=importlib`` pytest names a
test module after its path from the rootdir (``mcp.mcp-stats.tests.test_x``) and, when ``mcp`` is
not imported yet, registers a placeholder ``mcp`` package pointing at that directory. The real SDK
(``import mcp``) is then shadowed. Importing the SDK before collection keeps ``sys.modules["mcp"]``
the SDK; pytest only creates placeholders for missing parents.
"""

import mcp  # noqa: F401
