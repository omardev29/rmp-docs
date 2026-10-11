"""The Hypothesis settings every tests/test_*_property.py shares, and what
happens where Hypothesis is not installed -- the framework's
tests/hypothesis_profiles.py, for this repository.

    import hypothesis_profiles  # first: it skips the module, or fails it
    from hypothesis import given, strategies as st

Two profiles, chosen by RMP_HYPOTHESIS_PROFILE:

  ci        the default -- `python3 -m unittest discover -s tests` and every
            push. Derandomized: the same 200 examples a test on every run and
            every machine, so a red is the commit's and not the seed's. No
            example database, no deadline (a loaded runner makes timings
            meaningless), and the blob that reproduces a failure printed with
            it.
  nightly   5000 examples, random, and the database under .cache/hypothesis/
            -- where a counterexample found once is tried first on the next run
            in the same checkout.

Without Hypothesis -- `pip install hypothesis`, the version the framework's
thirdparty/FROZEN_VERSIONS.md pins in the build image -- a property module
says so and is skipped, unless RMP_REQUIRE_HYPOTHESIS=1: the pinned image has
it, and a skip there would be a green that tested nothing.

The modules under test are loaded by under_test.load(), as
`tools.rmpdocs.<name>`: see there why.

Standard library and Hypothesis only.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent

try:
    import hypothesis
except ImportError:
    if os.environ.get("RMP_REQUIRE_HYPOTHESIS") == "1":
        raise
    # Said once a run, however many property modules import this.
    if not os.environ.get("RMP_HYPOTHESIS_SKIP_SAID"):
        os.environ["RMP_HYPOTHESIS_SKIP_SAID"] = "1"
        print("  skip  the Hypothesis property tests: hypothesis is not installed "
              "(pip install hypothesis; RMP_REQUIRE_HYPOTHESIS=1 makes this a failure)",
              file=sys.stderr)
    raise unittest.SkipTest("hypothesis is not installed") from None

# differing_executors is off in both: unittest makes a TestCase per test, and
# mutmut runs the same suite twice in one process, so the same test meets a
# second `self` -- the check's whole trigger -- with nothing shared between
# the two.
_QUIET = [hypothesis.HealthCheck.differing_executors]

PROFILES = {
    "ci": dict(derandomize=True, max_examples=200, database=None, deadline=None,
               print_blob=True, suppress_health_check=_QUIET),
    # derandomize=False said, not left to the default: Hypothesis turns
    # derandomize on by itself where the CI variable is set -- every GitHub
    # runner -- and the nightly would run the same 5000 examples every night
    # (the framework's ce84f8f).
    "nightly": dict(derandomize=False, max_examples=5000, deadline=None, print_blob=True,
                    suppress_health_check=_QUIET,
                    database=hypothesis.database.DirectoryBasedExampleDatabase(
                        str(DOCS / ".cache" / "hypothesis"))),
}

for _name, _settings in PROFILES.items():
    hypothesis.settings.register_profile(_name, **_settings)

PROFILE = os.environ.get("RMP_HYPOTHESIS_PROFILE", "ci")
if PROFILE not in PROFILES:
    raise SystemExit(f"RMP_HYPOTHESIS_PROFILE={PROFILE!r}: one of {', '.join(PROFILES)}")
hypothesis.settings.load_profile(PROFILE)
