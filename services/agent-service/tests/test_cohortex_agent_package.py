"""Bootstrap smoke test (WP-00): the package installs and imports.

Replace with the acceptance tests named in the SRS when this component's work package starts.
"""

import cohortex_agent


def test_cohortex_agent_imports_with_version() -> None:
    assert cohortex_agent.__version__ == "0.0.0"
