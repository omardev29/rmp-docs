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


class LintTest(unittest.TestCase):
    """The wrong way that compiles: clang-tidy, with the framework's own
    .clang-tidy, has to refuse it with the check the page names; and the right
    way on a Guidelines page has to pass it with nothing said. Each kind of
    failure seen."""

    @classmethod
    def setUpClass(cls):
        CompileTest.setUpClass()
        if snippets.tidy() is None:
            if os.environ.get("RMP_DOCS_REQUIRE_COMPILE"):
                raise AssertionError("the compile tier is required here and there is no clang-tidy")
            raise unittest.SkipTest("no clang-tidy on PATH")

    def run_one(self, code, harness="toplevel", given="", **kw):
        s = snippets.Snippet("content/x.html", 1, "cpp", code, harness, given, **kw)
        return snippets.check([s], FRAMEWORK, jobs=1)[0][1]

    C_CAST = "int half() { return (int)3.5; }"
    CAST = "int half() { return static_cast<int>(3.5); }"

    def test_a_c_cast_is_refused_by_the_check_the_page_names(self):
        self.assertIsNone(self.run_one(self.C_CAST, expect_lint="modernize-avoid-c-style-cast"))

    def test_the_wrong_check_is_red(self):
        why = self.run_one(self.C_CAST, expect_lint="readability-redundant-casting")
        self.assertIn("clang-tidy does not say it", why)
        self.assertIn("[modernize-avoid-c-style-cast]", why)

    def test_code_the_check_passes_is_red(self):
        why = self.run_one(self.CAST, expect_lint="modernize-avoid-c-style-cast")
        self.assertIn("clang-tidy says nothing about it", why)

    def test_a_check_the_framework_does_not_run_is_red(self):
        why = self.run_one("// TODO: something\nint half() { return 1; }",
                           expect_lint="google-readability-todo")
        self.assertIn("the framework does not run google-readability-todo", why)

    def test_a_wrong_way_that_does_not_compile_is_red(self):
        why = self.run_one("int half() { return (int)nothing; }", expect_lint="modernize-avoid-c-style-cast")
        self.assertIn("does not compile", why)

    def test_the_right_way_has_to_be_clean(self):
        self.assertIsNone(self.run_one(self.CAST, lint_clean=True))
        why = self.run_one(self.C_CAST, lint_clean=True)
        self.assertIn("is shown as the right way", why)
        self.assertIn("line 1:", why)
        self.assertIn("[modernize-avoid-c-style-cast]", why)

    def test_only_the_blocks_own_lines_count(self):
        # The given is the reader's own code, and the harness is the site's.
        self.assertIsNone(self.run_one(self.CAST, given="inline int other() { return (int)2.5; }",
                                       lint_clean=True))

    def test_a_line_is_the_blocks_own_line(self):
        why = self.run_one("int one() { return 1; }\n\nint half() { return (int)3.5; }", lint_clean=True)
        self.assertIn("line 3:", why)


class GateExpectationTest(unittest.TestCase):
    """The wrong way that compiles and that a text gate of the framework
    refuses: tools/naming_check.sh, which reads every #if branch."""

    @classmethod
    def setUpClass(cls):
        CompileTest.setUpClass()
        if not (FRAMEWORK / "tools" / "naming_check.sh").is_file():
            raise unittest.SkipTest("no tools/naming_check.sh in the framework")

    def run_one(self, code, rule):
        s = snippets.Snippet("content/x.html", 1, "cpp", code, "toplevel",
                             expect_gate="naming", gate_rule=rule)
        return snippets.check([s], FRAMEWORK, jobs=1)[0][1]

    def test_a_k_constant_is_r2(self):
        self.assertIsNone(self.run_one("constexpr int kMaxLives = 3;", "R2"))

    def test_the_wrong_rule_is_red(self):
        why = self.run_one("constexpr int kMaxLives = 3;", "R1")
        self.assertIn("is shown as refused by R1", why)
        self.assertIn("[R2]", why)

    def test_a_name_the_gate_passes_is_red(self):
        why = self.run_one("constexpr int MAX_LIVES = 3;", "R2")
        self.assertIn("it says nothing", why)


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

    def test_a_refusal_says_what_refuses_it(self):
        self.assertIn("says which check",
                      self.build_with('<pre data-lang="cpp" data-harness="toplevel" '
                                      'data-expect="lint">int x;</pre>')[0])
        self.assertIn("says which, and which rule",
                      self.build_with('<pre data-lang="cpp" data-harness="toplevel" data-expect="gate" '
                                      'data-gate="nowhere" data-rule="R2">int x;</pre>')[0])
        self.assertIn("says which, and which rule",
                      self.build_with('<pre data-lang="cpp" data-harness="toplevel" data-expect="gate" '
                                      'data-gate="naming">int x;</pre>')[0])
        self.assertIn("the expectations are",
                      self.build_with('<pre data-lang="cpp" data-harness="toplevel" '
                                      'data-expect="warning">int x;</pre>')[0])

    def site_with(self, files: dict):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = Path(tmp)
        for name in ("site.toml", "reference.toml", "FRAMEWORK_REF"):
            shutil.copy(DOCS / name, root / name)
        shutil.copytree(DOCS / "templates", root / "templates")
        for rel, body in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(f"<!--\ntitle: T\ndescription: A page.\n-->\n<h1>T</h1>\n{body}\n")
        return Site(framework=FRAMEWORK, docs=root).build(write=False)

    def test_the_right_way_on_a_guidelines_page_is_held_clean(self):
        block = '<pre data-lang="cpp" data-harness="toplevel">int x = 0;</pre>'
        site = self.site_with({"content/index.html": block,
                               "content/guidelines/index.html": block + "\n" +
                               '<pre data-lang="cpp" data-harness="toplevel" data-expect="lint" '
                               'data-check="modernize-avoid-c-style-cast">int y = (int)1.5;</pre>'})
        by_page = {(s.page, s.expect_lint): s.lint_clean for s in site.snippets}
        self.assertEqual(by_page, {("content/index.html", ""): False,
                                   ("content/guidelines/index.html", ""): True,
                                   ("content/guidelines/index.html", "modernize-avoid-c-style-cast"): False})

    def test_a_refused_block_says_so_in_its_caption(self):
        site = self.site_with({"content/index.html":
                               '<pre data-lang="cpp" data-harness="toplevel" data-expect="lint" '
                               'data-check="modernize-avoid-c-style-cast">int y = (int)1.5;</pre>\n'
                               '<pre data-lang="cpp" data-harness="toplevel" data-expect="gate" '
                               'data-gate="naming" data-rule="R2">constexpr int kLives = 3;</pre>'})
        body = next(p for p in site.pages if p.url == "index.html").body
        self.assertEqual(body.count("expect-refused"), 2)
        self.assertIn("Compiles; <code>rmp lint</code> refuses it: "
                      "<code>modernize-avoid-c-style-cast</code>", body)
        self.assertIn("Compiles; <code>rmp test naming</code> refuses it: <code>R2</code>", body)

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

    def test_the_caret_stays_under_what_it_points_at(self):
        import html as h
        import re
        _problems, body = self.build_with(
            '<pre data-lang="toml" data-expect="reject">[window]\nvsync = "yes"\n</pre>')
        out = h.unescape(re.search(r'<pre class="compiler-output"[^>]*>(.*?)</pre>', body, re.S).group(1))
        lines = out.split("\n")
        line = next(i for i, x in enumerate(lines) if 'vsync = "yes"' in x)
        self.assertEqual(lines[line + 1].index("^"), lines[line].index("vsync"), out)

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
