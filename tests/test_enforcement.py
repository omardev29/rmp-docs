"""The enforcement gate reads the framework's .clang-tidy the way clang-tidy
does: the same checks on, the same off, for the framework and for the
examples. Held to clang-tidy's own --list-checks on the real files, every
check it knows, both ways -- a reader of the Checks globs that disagreed
with clang-tidy would pass a page that says a check runs where it does not.

Its red and green are tests/fixtures/gates/enforcement/ (test_gates_red).
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import checks, enforcement, snippets  # noqa: E402

FRAMEWORK = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))


class ReadingTest(unittest.TestCase):
    def test_a_folded_block_and_a_one_line_string(self):
        self.assertEqual(enforcement.checks_globs("Checks: >\n  -*,\n  misc-*,\n\n  -misc-x,\n# end\n"),
                         ["-*", "misc-*", "-misc-x"])
        self.assertEqual(enforcement.checks_globs("Checks: '-*,bugprone-*'\n"), ["-*", "bugprone-*"])

    def test_the_last_glob_that_matches_decides(self):
        globs = ["-*", "misc-*", "-misc-no-recursion", "misc-no-recursion-x"]
        self.assertTrue(enforcement.enabled("misc-const-correctness", globs))
        self.assertFalse(enforcement.enabled("misc-no-recursion", globs))
        self.assertFalse(enforcement.enabled("modernize-use-auto", globs))
        self.assertFalse(enforcement.enabled("anything", []))

    def test_custom_checks_are_named_as_clang_tidy_names_them(self):
        text = ("CustomChecks:\n  - Name: one\n    Query: |\n      match x\n  - Name: two-b\n"
                "CheckOptions:\n  - key: Name\n")
        self.assertEqual(enforcement.custom_names(text), ["custom-one", "custom-two-b"])

    def test_no_table_is_red_where_the_framework_has_a_clang_tidy(self):
        ctx = checks.Context.from_folder(DOCS / "tests" / "fixtures" / "gates" / "enforcement" / "good")
        ctx.sources = {path: text.replace("data-enforcement", "data-other")
                       for path, text in ctx.sources.items()}
        said = [str(p) for p in enforcement.check_enforcement(ctx)]
        self.assertTrue(any("no Guidelines page has the table" in s for s in said), said)

    def test_a_framework_rmp_new_cannot_list_is_said_once_not_row_by_row(self):
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(DOCS / "tests" / "fixtures" / "gates" / "enforcement" / "good", tmp / "good")
        # A fresh folder: game_paths() caches by path, and this one is new.
        (tmp / "good" / "framework" / "tools" / "rmp.py").write_text("import sys\nsys.exit(1)\n")
        said = [str(p) for p in enforcement.check_enforcement(checks.Context.from_folder(tmp / "good"))]
        self.assertEqual(len(said), 1, said)
        self.assertIn("rmp.py new --list` said nothing", said[0])


class AgreesWithClangTidyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = snippets.tidy()
        if not (FRAMEWORK / ".clang-tidy").is_file() or cls.binary is None:
            if os.environ.get("RMP_DOCS_REQUIRE_COMPILE"):
                raise AssertionError("required here: the framework's .clang-tidy and a clang-tidy")
            raise unittest.SkipTest("no framework .clang-tidy, or no clang-tidy on PATH")
        cls.conf = enforcement.configuration(str(FRAMEWORK))

    def listed(self, source, *extra):
        got = subprocess.run([self.binary, "--list-checks", *snippets.tidy_flags(self.binary), *extra,
                              str(FRAMEWORK / source)], capture_output=True, text=True, cwd=FRAMEWORK)
        return {line.strip() for line in got.stdout.splitlines() if line.startswith("    ")}

    def test_every_check_is_on_where_clang_tidy_runs_it_and_off_elsewhere(self):
        every = self.listed("src/main.cpp", "--checks=*")
        self.assertGreater(len(every), 300)
        for source, globs in (("src/main.cpp", self.conf["root"]),
                              ("examples/games/01_pong/src/main.cpp", self.conf["examples"])):
            on = self.listed(source)
            with self.subTest(config=source):
                self.assertTrue(on)
                ours = {c for c in every if enforcement.enabled(c, globs)}
                self.assertEqual(sorted(ours - on), [], "on here, off for clang-tidy")
                self.assertEqual(sorted(on - ours), [], "off here, on for clang-tidy")

    def test_the_custom_checks_are_the_ones_clang_tidy_registers(self):
        on = self.listed("src/main.cpp")
        customs = {c for c in on if c.startswith("custom-")}
        self.assertTrue(customs)
        self.assertEqual(customs, {c for c in self.conf["named"] if c.startswith("custom-")})


if __name__ == "__main__":
    unittest.main()
