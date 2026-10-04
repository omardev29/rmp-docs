"""Every gate fails on the thing it was written for, and passes without it.

For each gate registered in tools/rmpdocs/checks.py there is a folder
tests/fixtures/gates/<name>/ with bad/ and good/. bad/ has to make THAT gate
report a problem; good/ has to make it report none. A gate without both is a
failure here: a gate nobody has seen fail is a hope with a name.
"""

import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import checks, coverage, truth  # noqa: E402,F401

FIXTURES = DOCS / "tests" / "fixtures" / "gates"


class GatesGoRedTest(unittest.TestCase):
    def test_every_gate_has_both_fixtures(self):
        for name in checks.GATES:
            with self.subTest(gate=name):
                self.assertTrue((FIXTURES / name / "bad").is_dir(), f"no bad fixture for {name}")
                self.assertTrue((FIXTURES / name / "good").is_dir(), f"no good fixture for {name}")

    def test_no_fixture_without_a_gate(self):
        self.assertEqual(sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()),
                         sorted(checks.GATES))

    def test_bad_is_red_and_good_is_green(self):
        for name, (fn, _says) in checks.GATES.items():
            for kind in ("bad", "good"):
                folder = FIXTURES / name / kind
                if not folder.is_dir():
                    continue
                with self.subTest(gate=name, fixture=kind):
                    problems = fn(checks.Context.from_folder(folder))
                    if kind == "bad":
                        self.assertTrue(problems, f"{name} passed its bad fixture")
                        self.assertTrue(all(p.gate == name for p in problems))
                        # A gate with several rules lists, in expect.txt, a
                        # piece of the message each rule has to produce.
                        expect = folder / "expect.txt"
                        if expect.is_file():
                            said = "\n".join(str(p) for p in problems)
                            for piece in expect.read_text().splitlines():
                                if piece.strip():
                                    self.assertIn(piece, said, f"{name}: no problem says {piece!r}")
                    else:
                        self.assertEqual([str(p) for p in problems], [])


if __name__ == "__main__":
    unittest.main()
