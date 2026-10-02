"""Bootstrap smoke test (WP-00): the package installs and imports.

Replace with the acceptance tests named in the SRS when this component's work package starts.
"""

import cohortex_corpus


def test_cohortex_corpus_imports_with_version() -> None:
    assert cohortex_corpus.__version__ == "0.0.0"
