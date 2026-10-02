"""Bootstrap smoke test (WP-00): the package installs and imports.

Replace with the acceptance tests named in the SRS when this component's work package starts.
"""

import cohortex_mcp_docs


def test_cohortex_mcp_docs_imports_with_version() -> None:
    assert cohortex_mcp_docs.__version__ == "0.0.0"
