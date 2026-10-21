"""Bootstrap smoke test (WP-00): the package installs and imports.

Replace with the acceptance tests named in the SRS when this component's work package starts.
"""

import cohortex_evals


def test_cohortex_evals_imports_with_version() -> None:
    assert cohortex_evals.__version__ == "0.1.0"
