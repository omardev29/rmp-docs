"""The property tests and the mutation floor, held to the rules that make
them mean something -- each one a mistake that would pass in silence:

  - a property module imports hypothesis_profiles before Hypothesis (or it
    runs without the shared profile, randomized, and skips nowhere), loads
    what it tests through under_test.load() (or mutmut sees none of its
    calls), and has a @given (or it is a unit test with a misleading name);
  - every module a property test loads is a source of the floor (or
    nothing ever mutates the code it was written for), and
    every source and test the floor names exists (or mutmut runs nothing,
    and every mutant survives);
  - tests/mutation/run.sh is ASCII and parses (macOS's bash 3.2 included).
"""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
FLOOR = DOCS / "tests" / "mutation" / "floors" / "rmpdocs.txt"
RUN = DOCS / "tests" / "mutation" / "run.sh"
PROPERTY_FILES = sorted((DOCS / "tests").glob("test_*_property.py"))


def floor_field(name: str) -> list[str]:
    out = []
    for line in FLOOR.read_text(encoding="utf-8").splitlines():
        key, _, rest = line.strip().partition(" ")
        if key == name:
            out += rest.split()
    return out


class PropertyFilesTest(unittest.TestCase):

    def test_there_are_property_files(self):
        self.assertGreaterEqual(len(PROPERTY_FILES), 4)

    def test_each_one_loads_the_profile_first_and_its_modules_by_mutmut_s_name(self):
        for path in PROPERTY_FILES:
            with self.subTest(path.name):
                text = path.read_text(encoding="utf-8")
                profile = text.find("import hypothesis_profiles")
                self.assertGreaterEqual(profile, 0, "does not import hypothesis_profiles")
                self.assertLess(profile, text.find("from hypothesis import"),
                                "imports Hypothesis before hypothesis_profiles")
                self.assertIn("from under_test import load", text)
                self.assertNotRegex(text, r"(?m)^\s*(from|import) rmpdocs\b",
                                    "imports rmpdocs.<name>, which mutmut does not mutate")
                self.assertRegex(text, r"(?m)^    @given\(")


class FloorTest(unittest.TestCase):

    def test_what_the_floor_names_exists(self):
        for name in floor_field("sources") + floor_field("tests"):
            with self.subTest(name):
                self.assertTrue((DOCS / name).is_file(), f"{name}: no such file")

    def test_every_module_a_property_loads_is_mutated(self):
        sources = set(floor_field("sources"))
        for path in PROPERTY_FILES:
            for name in re.findall(r'\bload\("(\w+)"\)', path.read_text(encoding="utf-8")):
                with self.subTest(path.name, module=name):
                    self.assertIn(f"tools/rmpdocs/{name}.py", sources)

    def test_every_property_file_is_one_of_its_tests(self):
        tests = set(floor_field("tests"))
        for path in PROPERTY_FILES + [DOCS / "tests" / "test_counterexamples.py"]:
            with self.subTest(path.name):
                self.assertIn(f"tests/{path.name}", tests)

    def test_the_floor_is_a_number_or_not_measured(self):
        self.assertRegex(" ".join(floor_field("floor")), r"\A(\d{1,2}|100|-)\Z")
        self.assertEqual(floor_field("kind"), ["py"])

    def test_the_runner_is_ascii_and_parses(self):
        data = RUN.read_bytes()
        self.assertTrue(all(b < 128 for b in data), "a non-ASCII byte in tests/mutation/run.sh")
        self.assertEqual(subprocess.run(["bash", "-n", str(RUN)], capture_output=True).returncode, 0)

    def test_the_runner_says_what_it_needs(self):
        out = subprocess.run(["bash", str(RUN), "nonsense", "x", "y"], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 2)
        self.assertIn("usage:", out.stdout)

    def test_the_runner_says_it_has_no_checker(self):
        # It once exited 1 having said nothing: the message went into $(...).
        out = subprocess.run(["bash", str(RUN), "check"], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, env={**os.environ, "RMP_FRAMEWORK": "/nonexistent"})
        self.assertEqual(out.returncode, 1)
        self.assertIn("no tools/mutation_report.py", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
