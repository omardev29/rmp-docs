"""C and C++ blocks: each one compiled, each kind of failure seen.

The compile half needs the framework next to this repository with its
build/lint configured (`python3 tools/configure.py && cmake --preset lint`);
without it, it skips here -- and the site's CI, which configures it, runs it.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import snippets  # noqa: E402
from rmpdocs.site import Site  # noqa: E402

FRAMEWORK = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))


class CompileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (FRAMEWORK / "build" / "lint" / "compile_commands.json").is_file():
            if os.environ.get("RMP_DOCS_REQUIRE_COMPILE"):
                raise AssertionError("the compile tier is required here and build/lint is missing")
            raise unittest.SkipTest("the framework's build/lint is not configured")

    def run_one(self, code, harness="function", given="", expect_error=False, error_text=""):
        s = snippets.Snippet("content/x.html", 1, "cpp", code, harness, given,
                             expect_error=expect_error, error_text=error_text)
        return snippets.check([s], FRAMEWORK, jobs=1)[0][1]

    def test_a_good_block_passes(self):
        self.assertIsNone(self.run_one('if (rmp::ui::button("Play")) play();', given="void play();"))

    def test_a_broken_block_is_red(self):
        why = self.run_one("rmp::ui::buton(\"Play\");")
        self.assertIn("does not compile in the function harness", why)

    def test_a_mistake_that_compiles_is_red(self):
        why = self.run_one("int x = 1;", expect_error=True, error_text="anything")
        self.assertIn("compiles", why)

    def test_a_mistake_must_say_what_the_page_says(self):
        # An error both GCC and Clang word the same way. (Designators out of
        # order are NOT one: GCC refuses them, Clang only warns.)
        code = "rmp::ui::button(42);"
        self.assertIsNotNone(self.run_one(code, expect_error=True, error_text="no such words"))
        self.assertIsNone(self.run_one(code, expect_error=True, error_text="no matching function"))

    def test_every_harness_compiles_an_empty_snippet(self):
        for name in snippets.harness_names():
            with self.subTest(harness=name):
                s = snippets.Snippet("content/x.html", 1, "c" if name == "c99" else "cpp", "", name)
                self.assertIsNone(snippets.check([s], FRAMEWORK, jobs=1)[0][1])


class StaticRuleTest(unittest.TestCase):
    """A block nothing compiles is refused at build time, before any compiler."""

    def build_with(self, block):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("site.toml", "reference.toml", "FRAMEWORK_REF"):
                shutil.copy(DOCS / name, root / name)
            shutil.copytree(DOCS / "templates", root / "templates")
            (root / "content").mkdir()
            (root / "content" / "index.html").write_text(
                f"<!--\ntitle: T\ndescription: A page.\n-->\n<h1>T</h1>\n{block}\n")
            site = Site(framework=FRAMEWORK if FRAMEWORK.is_dir() else None, docs=root).build(write=False)
            return [str(p) for p in site.problems if p.gate == "snippets"]

    def setUp(self):
        if not (FRAMEWORK / "include" / "rmp").is_dir():
            self.skipTest("no framework next to rmp-docs")

    def test_a_block_without_a_harness_is_refused(self):
        got = self.build_with('<pre data-lang="cpp">int x;</pre>')
        self.assertEqual(len(got), 1)
        self.assertIn("nothing compiles", got[0])

    def test_an_unknown_harness_and_a_mistake_without_its_error(self):
        self.assertIn("is not a file in snippets/harness",
                      self.build_with('<pre data-lang="cpp" data-harness="nowhere">int x;</pre>')[0])
        self.assertIn("says which error",
                      self.build_with('<pre data-lang="cpp" data-harness="function" '
                                      'data-expect="error">int x;</pre>')[0])

    def test_a_harnessed_block_is_recorded(self):
        self.assertEqual(self.build_with('<pre data-lang="cpp" data-harness="function">int x;</pre>'), [])

    def test_a_mistake_looks_like_one_and_says_what_the_compiler_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("site.toml", "reference.toml", "FRAMEWORK_REF"):
                shutil.copy(DOCS / name, root / name)
            shutil.copytree(DOCS / "templates", root / "templates")
            (root / "content").mkdir()
            (root / "content" / "index.html").write_text(
                "<!--\ntitle: T\ndescription: A page.\n-->\n<h1>T</h1>\n"
                '<pre data-lang="cpp" data-harness="function" data-expect="error" '
                'data-error="no matching function">rmp::ui::button(42);</pre>\n'
                '<pre data-lang="cpp" data-harness="function">int fine = 0;</pre>\n')
            site = Site(framework=FRAMEWORK, docs=root).build(write=False)
            body = next(p for p in site.pages if p.url == "index.html").body
        self.assertEqual(body.count("expect-error"), 1)
        self.assertIn("Does not compile", body)
        self.assertIn("saying among other things: <code>no matching function</code>", body)


if __name__ == "__main__":
    unittest.main()


class TomlTest(unittest.TestCase):
    """Every .toml block goes through the framework's configure.py."""

    def setUp(self):
        if not (FRAMEWORK / "tools" / "configure.py").is_file():
            self.skipTest("no framework next to rmp-docs")

    def build_with(self, block):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("site.toml", "reference.toml", "FRAMEWORK_REF"):
                shutil.copy(DOCS / name, root / name)
            shutil.copytree(DOCS / "templates", root / "templates")
            (root / "content").mkdir()
            (root / "content" / "index.html").write_text(
                f"<!--\ntitle: T\ndescription: A page.\n-->\n<h1>T</h1>\n{block}\n")
            site = Site(framework=FRAMEWORK, docs=root).build(write=False)
            page = next(p for p in site.pages if p.url == "index.html")
            return [str(p) for p in site.problems if p.gate == "toml"], page.body

    def test_a_valid_block_passes(self):
        problems, _ = self.build_with('<pre data-lang="toml">[window]\nvsync = false\n</pre>')
        self.assertEqual(problems, [])

    def test_an_invalid_block_is_red(self):
        problems, _ = self.build_with('<pre data-lang="toml">[window]\nvsync = "yes"\n</pre>')
        self.assertEqual(len(problems), 1)
        self.assertIn("configure.py refuses this", problems[0])

    def test_a_refusal_shows_the_real_words(self):
        problems, body = self.build_with(
            '<pre data-lang="toml" data-expect="reject">[window]\nvsync = "yes"\n</pre>')
        self.assertEqual(problems, [])
        self.assertIn('class="compiler-output"', body)
        self.assertIn("[window] vsync", body)

    def test_a_refusal_that_is_taken_is_red(self):
        problems, _ = self.build_with(
            '<pre data-lang="toml" data-expect="reject">[window]\nvsync = true\n</pre>')
        self.assertIn("configure.py takes it", problems[0])

    def test_a_block_that_is_not_the_config_says_why(self):
        problems, _ = self.build_with('<pre data-lang="toml" data-config="no">[x]\ny = 1\n</pre>')
        self.assertIn("needs a data-reason", problems[0])
        problems, _ = self.build_with(
            '<pre data-lang="toml" data-config="no" data-reason="site.toml">[x]\ny = 1\n</pre>')
        self.assertEqual(problems, [])
