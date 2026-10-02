"""Bootstrap smoke test (WP-00): the package installs and imports.

Replace with the acceptance tests named in the SRS when this component's work package starts.
"""

import cohortex_analytics


def test_cohortex_analytics_imports_with_version() -> None:
    assert cohortex_analytics.__version__ == "0.0.0"
