"""Bootstrap smoke test (WP-00): the package installs and imports.

Replace with the acceptance tests named in the SRS when this component's work package starts.
"""

import cohortex_ingest


def test_cohortex_ingest_imports_with_version() -> None:
    assert cohortex_ingest.__version__ == "0.0.0"
