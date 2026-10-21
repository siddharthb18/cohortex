"""Shared plumbing for the Cohortex MCP servers (mcp-fleet, mcp-stats, later mcp-docs).

Everything a tool needs that is not the tool's own logic lives here:

- ``contracts``: find ``contracts/tools/`` and load schemas and the manifest.
- ``manifest``: SHA-256 pinning of tool descriptions and input schemas (FR-TOOL-5).
- ``errors``: the structured error body returned with ``isError: true`` (FR-TOOL-2).
- ``envelope``: the evidence envelope and the 4 KB cap with lossless paging (FR-TOOL-3, FR-TOOL-6).
- ``server``: builds an MCP SDK 2.x low-level ``Server`` from tool specs, plus HTTP/stdio runners.
"""

__version__ = "0.1.0"
