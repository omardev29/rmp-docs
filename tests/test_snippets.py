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

    def test_a_compiler_warning_the_framework_turns_on(self):
        # -Wshadow, which the framework's .clang-tidy passes and enables as
        # clang-diagnostic-shadow; --list-checks does not name it.
        code = "struct Pass { int number = 0; } pass;\nvoid draw(int pass) { (void)pass; }"
        self.assertIsNone(self.run_one(code, expect_lint="clang-diagnostic-shadow"))

    def test_a_compiler_warning_it_does_not_turn_on_is_red(self):
        why = self.run_one("void f() { int unused = 0; }", expect_lint="clang-diagnostic-unused-variable")
        self.assertIn("clang-tidy", why)
        self.assertIn("does not say it", why)

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

    # Refused by a query of the framework's own .clang-tidy (CustomChecks) and
    # by nothing else clang-tidy has: the pointer is written through, so no
    # const-correctness or readability check speaks.
    RAW_POINTER = "void zero(int *value) { *value = 0; }"

    def need_custom_checks(self):
        if not snippets.has_custom_checks(FRAMEWORK):
            self.skipTest("this framework's .clang-tidy has no CustomChecks")

    def test_a_raw_pointer_is_refused_by_the_frameworks_own_query(self):
        self.need_custom_checks()
        self.assertIsNone(self.run_one(self.RAW_POINTER, expect_lint="custom-rmp-raw-pointer"))

    def test_the_right_way_is_held_to_the_custom_checks(self):
        # Seen red without --experimental-custom-checks: clang-tidy then
        # registers no custom check, says nothing, and the block passed.
        self.need_custom_checks()
        why = self.run_one(self.RAW_POINTER, lint_clean=True)
        self.assertIn("is shown as the right way", why)
        self.assertIn("[custom-rmp-raw-pointer]", why)

    def test_a_clang_tidy_that_cannot_run_them_is_refused(self):
        self.need_custom_checks()
        real = snippets.tidy_supports_custom
        snippets.tidy_supports_custom = lambda binary: False
        try:
            for kw in ({"lint_clean": True}, {"expect_lint": "modernize-avoid-c-style-cast"}):
                with self.subTest(**kw):
                    why = self.run_one(self.CAST if "lint_clean" in kw else self.C_CAST, **kw)
                    self.assertIn("has CustomChecks", why)
                    self.assertIn("--experimental-custom-checks", why)
        finally:
            snippets.tidy_supports_custom = real

    def test_a_query_that_does_not_parse_is_red_not_quiet(self):
        # clang-tidy prints one "Error parsing" line, exits 0 and never runs
        # the check: the block would pass as the right way.
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "include").symlink_to(FRAMEWORK / "include")
        (tmp / ".clang-tidy").write_text(
            "Checks: '-*,custom-*'\nCustomChecks:\n  - Name: broken\n    Query: |\n"
            "      match varDecl(hasType(pointerType()).bind(\"p\")\n    Diagnostic:\n"
            "      - BindName: p\n        Level: Warning\n        Message: \"p\"\n")
        s = snippets.Snippet("content/x.html", 1, "cpp", self.RAW_POINTER, "toplevel", lint_clean=True)
        found = snippets.lint_one(s, tmp, snippets.compile_command(FRAMEWORK), snippets.tidy())
        self.assertEqual([name for name, _l, _w in found], ["clang-tidy"])
        self.assertIn("did not parse", found[0][2])
        self.assertIn("Error parsing", found[0][2])


class StyleTest(unittest.TestCase):
    """Every block that is not shown as a mistake, and every file a tutorial
    writes, passes the framework's tools/style_check.sh: `++i`, no C cast, no
    NULL. Seen red on the fifteen postfix increments the pages had."""

    def setUp(self):
        if not (FRAMEWORK / snippets.STYLE_CHECK).is_file():
            if os.environ.get("RMP_DOCS_REQUIRE_COMPILE"):
                raise AssertionError("the compile tier is required here and there is no style_check.sh")
            self.skipTest("no tools/style_check.sh in the framework")

    def block(self, code, lang="cpp", **kw):
        return snippets.Snippet("content/x.html", 1, lang, code, "function", **kw)

    def test_a_postfix_increment_is_red_on_its_line(self):
        got = snippets.style([self.block("int n = 0;\nn++;")], FRAMEWORK)
        self.assertEqual([(line, what.split()[0]) for _b, line, what in got], [(2, "S6")])

    def test_the_prefix_one_and_a_used_value_pass(self):
        self.assertEqual(snippets.style([self.block("int n = 0;\n++n;\nconst int m = n++;")], FRAMEWORK), [])

    def test_c_is_c(self):
        self.assertEqual(snippets.style([self.block("int i = 0; i++; void *p = NULL;", lang="c")],
                                        FRAMEWORK), [])

    def test_a_mistake_on_purpose_is_not_held_to_it(self):
        for kw in ({"expect_error": True}, {"expect_lint": "modernize-avoid-c-style-cast"},
                   {"expect_gate": "style"}):
            with self.subTest(**kw):
                self.assertEqual(snippets.style([self.block("int n = 0; n++;", **kw)], FRAMEWORK), [])

    def test_a_tutorial_file_is_held_too(self):
        from rmpdocs.project import ProjectFile
        f = ProjectFile("content/getting-started/x.html", 10, "src/scenes/game.h", "void f(int &n) { n++; }",
                        "cpp")
        got = snippets.style([f], FRAMEWORK)
        self.assertEqual(len(got), 1)
        self.assertIs(got[0][0], f)

    def test_a_page_can_show_a_raylib_load_refused_by_ownership(self):
        CompileTest.setUpClass()
        if not (FRAMEWORK / "tools" / "ownership_check.sh").is_file():
            self.skipTest("no tools/ownership_check.sh in the framework")
        s = snippets.Snippet("content/x.html", 1, "cpp",
                             'Texture2D picture = LoadTexture("rabbit.png");\nUnloadTexture(picture);',
                             "function", expect_gate="ownership", gate_rule="O2")
        self.assertIsNone(snippets.check([s], FRAMEWORK, jobs=1)[0][1])
        s.gate_rule = "O1"
        self.assertIn("is shown as refused by O1", snippets.check([s], FRAMEWORK, jobs=1)[0][1])

    def test_a_page_can_show_it_refused(self):
        CompileTest.setUpClass()
        s = snippets.Snippet("content/x.html", 1, "cpp", "int count() { int n = 0; n++; return n; }",
                             "toplevel", expect_gate="style", gate_rule="S6")
        self.assertIsNone(snippets.check([s], FRAMEWORK, jobs=1)[0][1])
        s.gate_rule = "S1"
        self.assertIn("is shown as refused by S1", snippets.check([s], FRAMEWORK, jobs=1)[0][1])


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


class RightWayGatesTest(unittest.TestCase):
    """The right way on a Guidelines page passes the framework's text gates
    too: what clang-tidy cannot see -- `other._x`, a g_ name, a constant named
    like a macro, a raylib Load* outside its owner -- and, for a block that is a
    public header, a pointer a game could name. Each refusal seen."""

    @classmethod
    def setUpClass(cls):
        CompileTest.setUpClass()
        for script in ("naming_check.sh", "ownership_check.sh", "pointer_check.py"):
            if not (FRAMEWORK / "tools" / script).is_file():
                raise unittest.SkipTest(f"no tools/{script} in the framework")

    def run_one(self, code, harness="toplevel"):
        s = snippets.Snippet("content/guidelines/x.html", 1, "cpp", code, harness, gates_clean=True)
        return snippets.check([s], FRAMEWORK, jobs=1)[0][1]

    def test_a_clean_block_passes(self):
        self.assertIsNone(self.run_one("constexpr int MAX_LIVES = 3;\nint score = 0;"))

    def test_a_name_only_the_naming_gate_sees_is_refused(self):
        # clang-tidy's readability-identifier-naming passes both: g_score is
        # lower_case, and it does not look at a member reached through a dot.
        for code, rule in (("int g_score = 0;", "R1"),
                           ("class Wallet {\npublic:\n    [[nodiscard]] bool richer(const Wallet &other) const {\n"
                            "        return _coins > other._coins;\n    }\n\nprivate:\n    int _coins = 0;\n};",
                            "R4"),
                           ("constexpr int MAX = 10;", "R6")):
            with self.subTest(rule=rule):
                why = self.run_one(code)
                self.assertIn("is shown as the right way, and tools/naming_check.sh refuses it", why)
                self.assertIn(f": {rule} ", why)

    def test_a_raylib_resource_made_outside_its_owner_is_refused(self):
        why = self.run_one('const Texture2D rabbit = LoadTexture("rabbit.png");\n'
                           "UnloadTexture(rabbit);", harness="function")
        self.assertIn("is shown as the right way, and tools/ownership_check.sh refuses it", why)
        self.assertIn("O2 LoadTexture", why)

    def test_a_public_header_with_a_pointer_is_refused(self):
        if shutil.which("clang++") is None:
            self.skipTest("tools/pointer_check.py reads the headers with clang++")
        code = ("#pragma once\n\n#include <string_view>\n\nnamespace rmp {\nclass Object;\n\n"
                "Object *find(std::string_view name);\n} // namespace rmp")
        why = self.run_one(code, harness=snippets.HEADER)
        self.assertIn("is shown as the right way, and tools/pointer_check.py refuses it", why)
        self.assertIn("rmp::find -- returns `Object *`", why)
        # The same header with what the page says instead passes.
        self.assertIsNone(self.run_one(code.replace("class Object;", "class Object;\n"
                                                    "template <class T> class Ref;")
                                       .replace("Object *find", "Ref<Object> find"),
                                       harness=snippets.HEADER))

    def test_a_pointer_outside_a_header_is_not_the_pointer_gates(self):
        # tools/pointer_check.py reads public headers; a .cpp block's pointer
        # is clang-tidy's business (custom-rmp-raw-pointer), not this gate's.
        self.assertIsNone(self.run_one("void zero(int &value) { value = 0; }"))


class RightWayGatesRunTest(unittest.TestCase):
    """A text gate the right way is held to has to run and say nothing. One the
    framework does not have, or one that fails without naming a line -- a
    crash, or tools/pointer_check.py with no clang++ to read the header with --
    is a problem, not a pass. The framework here is stand-in scripts, so no
    compiler is needed to see it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fw = self.tmp / "framework"
        (self.fw / "include" / "rmp").mkdir(parents=True)
        (self.fw / "tools").mkdir()
        for script in ("naming_check.sh", "ownership_check.sh"):
            self.script(script, "exit 0\n")
        # pointer_check.py's own behaviour: no clang++ is a skip, and exit 0,
        # unless RMP_REQUIRE_CLANG=1 makes it a failure.
        self.script("pointer_check.py",
                    "import os, sys\n"
                    "if os.environ.get('RMP_REQUIRE_CLANG') == '1':\n"
                    "    print('FAIL: no clang++ to read the headers with, and RMP_REQUIRE_CLANG=1')\n"
                    "    sys.exit(1)\n"
                    "print('  skip  no clang++ on PATH: the public headers\\' pointers were not read')\n")

    def script(self, name, text):
        (self.fw / "tools" / name).write_text(text)

    def judge(self, code="int score = 0;", harness="toplevel"):
        s = snippets.Snippet("content/guidelines/x.html", 1, "cpp", code, harness, gates_clean=True)
        (self.tmp / "unit").mkdir(exist_ok=True)
        unit = snippets.materialise(s, self.fw, self.tmp / "unit")
        return snippets.clean_gates(s, unit, self.fw)

    def test_gates_that_run_and_say_nothing_pass(self):
        self.assertIsNone(self.judge())

    def test_a_gate_the_framework_does_not_have_is_a_problem(self):
        (self.fw / "tools" / "ownership_check.sh").unlink()
        self.assertIn("the framework has no tools/ownership_check.sh", self.judge() or "passed")

    def test_a_gate_that_fails_without_naming_a_line_is_a_problem(self):
        self.script("naming_check.sh", "echo 'Traceback (most recent call last):' >&2\n"
                                       "echo \"NameError: name 'tree' is not defined\" >&2\nexit 1\n")
        why = self.judge() or "passed"
        self.assertIn("tools/naming_check.sh failed without naming a line (exit 1)", why)
        self.assertIn("NameError: name 'tree' is not defined", why)

    def test_a_header_no_clang_could_read_is_a_problem(self):
        why = self.judge("#pragma once\n\nnamespace game {\ninline constexpr int LIVES = 3;\n}",
                         harness=snippets.HEADER) or "passed"
        self.assertIn("tools/pointer_check.py failed without naming a line (exit 1)", why)
        self.assertIn("no clang++ to read the headers with", why)

    def test_a_finding_on_the_harness_alone_is_not_the_blocks(self):
        # The unit is the harness around the block: a FAIL line about one of
        # the harness's lines is neither a finding of the block's nor a crash.
        self.script("naming_check.sh", 'echo "FAIL  $1:1: R1 g_x -- a g_ name"\nexit 1\n')
        self.assertIsNone(self.judge())

    def test_a_finding_on_the_block_is_refused(self):
        self.script("naming_check.sh", 'for i in $(seq 1 400); do echo "FAIL  $1:$i: R1 g_x -- a g_ name"; done\n'
                                       "exit 1\n")
        self.assertIn("is shown as the right way, and tools/naming_check.sh refuses it",
                      self.judge() or "passed")


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
        by_page = {(s.page, s.expect_lint): (s.lint_clean, s.format_clean, s.gates_clean)
                   for s in site.snippets}
        self.assertEqual(by_page, {("content/index.html", ""): (False, False, False),
                                   ("content/guidelines/index.html", ""): (True, True, True),
                                   ("content/guidelines/index.html", "modernize-avoid-c-style-cast"):
                                   (False, False, False)})

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


class ShownTest(unittest.TestCase):
    """What a tool printed, as the page shows it: the block's own diagnostics,
    the file called snippet.cpp and the lines the block's own. No compiler:
    the tool's output is given, so each rule of the rewriting is seen alone."""

    def unit(self, first=40, last=42):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        f = tmp / "snippet.cpp"
        f.write_text("")
        return snippets.Unit(f, f, first, last, "snippet.cpp", []), tmp

    def test_a_diagnostic_is_renumbered_to_the_blocks_line(self):
        u, tmp = self.unit()
        out = (f"{u.unit}:41:9: warning: variable 'total' can be declared 'const' [misc-const-correctness]\n"
               "   41 |         int total = a + b;\n"
               "      |         ^\n"
               "      |             const \n"
               "1 warning generated.\n")
        got = snippets.shown(out, u)
        self.assertEqual(got.splitlines(), [
            "snippet.cpp:2:9: warning: variable 'total' can be declared 'const' [misc-const-correctness]",
            "    2 |         int total = a + b;",
            "      |         ^",
            "      |             const"])
        self.assertNotIn(str(tmp), got)

    def test_a_source_line_of_the_harness_is_not_shown(self):
        # clang-tidy prints the line above a fix as context: the harness's.
        u, _tmp = self.unit()
        out = (f"{u.unit}:40:35: warning: prefer 'std::numbers::pi_v<float>' [modernize-use-std-numbers]\n"
               "   39 | // given\n"
               "      | ~~\n"
               "   40 | float t() { return 3.14159265f; }\n"
               "      |                    ^~~~~~~~~~~\n")
        self.assertEqual(snippets.shown(out, u).splitlines(), [
            "snippet.cpp:1:35: warning: prefer 'std::numbers::pi_v<float>' [modernize-use-std-numbers]",
            "    1 | float t() { return 3.14159265f; }",
            "      |                    ^~~~~~~~~~~"])

    def test_what_is_not_on_the_blocks_lines_is_not_shown(self):
        u, _tmp = self.unit()
        out = (f"{u.unit}:12:1: warning: about the harness [misc-x]\n"
               f"/fw/include/rmp/ui.h:3:1: note: about a header\n"
               f"In file included from {u.unit}:2:\n"
               f"{u.unit}:40:1: error: about the block\n")
        self.assertEqual(snippets.shown(out, u), "snippet.cpp:1:1: error: about the block")

    def test_the_words_the_page_names_are_shown_even_from_a_header(self):
        u, _tmp = self.unit()
        fw = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fw, True)
        (fw / "include" / "rmp").mkdir(parents=True)
        out = (f"{u.unit}:40:1: error: no matching function for call to 'button'\n"
               f"{fw}/include/rmp/ui.h:9:6: note: candidate function not viable: no known conversion\n"
               "    9 | bool button(std::string_view label);\n")
        got = snippets.shown(out, u, keep="no known conversion", framework=fw)
        self.assertIn("snippet.cpp:1:1: error: no matching function", got)
        self.assertIn("include/rmp/ui.h:9:6: note: candidate function not viable", got)
        self.assertIn("    9 | bool button", got)
        self.assertNotIn(str(fw), got)

    def test_a_place_inside_a_message_is_the_blocks_too(self):
        u, tmp = self.unit()
        out = (f"{u.unit}:42:3: note: in call to '(unnamed struct at {u.unit}:40:11)()'\n"
               "   42 | } generator;\n")
        got = snippets.shown(out, u)
        self.assertEqual(got.splitlines()[0],
                         "snippet.cpp:3:3: note: in call to '(unnamed struct at snippet.cpp:1:11)()'")
        self.assertNotIn(str(tmp), got)

    def test_an_error_in_a_header_comes_where_the_tool_put_it(self):
        # A template's error is in the header; the notes that lead back to
        # the block come after it, and clang repeats them.
        u, _tmp = self.unit()
        out = (f"/usr/lib/gcc/x86_64-linux-gnu/13/../../../../include/c++/13/bits/std_function.h:429:18: "
               "error: static assertion failed: std::function target must be copy-constructible\n"
               f"{u.unit}:41:32: note: in instantiation of 'function' requested here\n"
               f"{u.unit}:41:32: note: in instantiation of 'function' requested here\n")
        got = snippets.shown(out, u, keep="copy-constructible").splitlines()
        self.assertEqual(got, [
            "c++/13/bits/std_function.h:429:18: error: static assertion failed: "
            "std::function target must be copy-constructible",
            "snippet.cpp:2:32: note: in instantiation of 'function' requested here"])

    def test_a_long_report_is_cut(self):
        u, _tmp = self.unit(first=1, last=50)
        out = "".join(f"{u.unit}:{n}:1: warning: number {n} [x]\n" for n in range(1, 20))
        got = snippets.shown(out, u).splitlines()
        self.assertEqual(len(got), snippets.SHOWN_DIAGNOSTICS + 1)
        self.assertEqual(got[-1], "…")

    def test_clang_formats_source_line_stays_with_its_warning(self):
        u, _tmp = self.unit(first=1, last=3)
        out = (f"{u.unit}:1:6: warning: code should be clang-formatted [-Wclang-format-violations]\n"
               "int x     = 1;\n"
               "     ^\n")
        self.assertEqual(snippets.shown(out, u).splitlines(), [
            "snippet.cpp:1:6: warning: code should be clang-formatted [-Wclang-format-violations]",
            "int x     = 1;", "     ^"])


class SaidTest(unittest.TestCase):
    """A block shown refused keeps the tool's own words about it, for the
    page: never typed, and about the block's own lines."""

    @classmethod
    def setUpClass(cls):
        LintTest.setUpClass()

    def judged(self, code, harness="toplevel", **kw):
        s = snippets.Snippet("content/x.html", 1, "cpp", code, harness, **kw)
        why = snippets.check([s], FRAMEWORK, jobs=1)[0][1]
        self.assertIsNone(why)
        self.assertNotIn("/tmp", s.said)
        self.assertNotIn(str(FRAMEWORK), s.said)
        return s.said

    def test_clang_tidy_says_it_on_the_blocks_line(self):
        said = self.judged("int one() { return 1; }\n\nint half() { return (int)3.5; }",
                           expect_lint="modernize-avoid-c-style-cast")
        self.assertRegex(said, r"^snippet\.cpp:3:\d+: warning: .*\[modernize-avoid-c-style-cast\]")
        self.assertRegex(said, r"(?m)^\s+3 \| int half\(\)")

    def test_a_gate_says_it_with_its_rule(self):
        said = self.judged("\nconstexpr int kMaxLives = 3;", expect_gate="naming", gate_rule="R2")
        self.assertRegex(said, r"^FAIL\s+snippet\.cpp:2: R2 kMaxLives -- ")

    def test_the_compiler_says_it_in_its_words(self):
        said = self.judged("int fine = 0;\nrmp::ui::button(42);", harness="function",
                           expect_error=True, error_text="no matching function")
        self.assertIn("no matching function", said)
        self.assertRegex(said, r"(?m)^snippet\.cpp:2:\d+: error: ")


class HeaderHarnessTest(unittest.TestCase):
    """The block is a header of the framework's own, include/rmp/snippet.h:
    what the checks that look only at headers see."""

    @classmethod
    def setUpClass(cls):
        LintTest.setUpClass()
        if not snippets.has_custom_checks(FRAMEWORK):
            raise unittest.SkipTest("this framework's .clang-tidy has no CustomChecks")

    def run_one(self, code, **kw):
        s = snippets.Snippet("content/x.html", 1, "cpp", code, snippets.HEADER, **kw)
        return snippets.check([s], FRAMEWORK, jobs=1)[0][1], s

    def test_a_constant_in_a_header_is_inline_constexpr(self):
        # Seen red in a .cpp: the query reads headers only, and the toplevel
        # harness is not one.
        code = "#pragma once\n\nnamespace rmp {\nconst int LIVES = 3;\n} // namespace rmp"
        why, s = self.run_one(code, expect_lint="custom-rmp-header-constant")
        self.assertIsNone(why)
        self.assertRegex(s.said, r"^include/rmp/snippet\.h:4:\d+: warning: a constant in a header")
        right = "#pragma once\n\nnamespace rmp {\ninline constexpr int LIVES = 3;\n} // namespace rmp"
        self.assertIsNone(self.run_one(right, lint_clean=True)[0])

    def test_the_block_is_the_header_and_sees_the_framework(self):
        why, _s = self.run_one("#pragma once\n\ninline rmp::Texture empty_texture() { return {}; }",
                               lint_clean=True)
        self.assertIsNone(why)


class PointersGateTest(unittest.TestCase):
    """tools/pointer_check.py reads the block as the public header it is."""

    @classmethod
    def setUpClass(cls):
        CompileTest.setUpClass()
        if not (FRAMEWORK / "tools" / "pointer_check.py").is_file():
            raise unittest.SkipTest("no tools/pointer_check.py in the framework")
        if shutil.which("clang++") is None:
            raise unittest.SkipTest("tools/pointer_check.py reads the headers with clang++")

    WRONG = ("#pragma once\n\n#include <string_view>\n\nnamespace rmp {\nclass Object;\n\n"
             "Object *find(std::string_view name);\n} // namespace rmp")

    def run_one(self, code, harness=snippets.HEADER):
        s = snippets.Snippet("content/x.html", 1, "cpp", code, harness, expect_gate="pointers")
        return snippets.check([s], FRAMEWORK, jobs=1)[0][1], s

    def test_a_pointer_a_game_can_name_is_refused(self):
        why, s = self.run_one(self.WRONG)
        self.assertIsNone(why)
        self.assertIn("FAIL: include/rmp/snippet.h:8: rmp::find -- returns", s.said)
        self.assertIn("a raw pointer or a C string in rmp's API", s.said.splitlines()[-1])

    def test_a_header_it_passes_is_red(self):
        why, _s = self.run_one(self.WRONG.replace("Object *find", "bool exists"))
        self.assertIn("is shown as refused by tools/pointer_check.py, and it says nothing", why)

    def test_it_reads_headers_only(self):
        why, _s = self.run_one("void zero(int *value);", harness="toplevel")
        self.assertIn('give it data-harness="header"', why)


class FormatTest(unittest.TestCase):
    """clang-format, with the framework's .clang-format: a block shown refused
    by it, and the right way on a Guidelines page held to it."""

    @classmethod
    def setUpClass(cls):
        CompileTest.setUpClass()
        problem = snippets.format_problem(FRAMEWORK)
        if problem:
            if os.environ.get("RMP_DOCS_REQUIRE_COMPILE"):
                raise AssertionError(f"the compile tier is required here and {problem}")
            raise unittest.SkipTest(problem)

    WRONG = "int lives     = 3;\nint *score = nullptr;"
    # Four spaces and `int *`: the framework's file, not LLVM's two.
    RIGHT = "int lives = 3;\nint *score = nullptr;\n\nstruct Score {\n    int points = 0;\n};"

    def run_one(self, code, **kw):
        s = snippets.Snippet("content/x.html", 1, "cpp", code, "toplevel", **kw)
        return snippets.check([s], FRAMEWORK, jobs=1)[0][1], s

    def test_a_block_clang_format_would_change_is_refused_in_its_words(self):
        why, s = self.run_one(self.WRONG, expect_gate="format")
        self.assertIsNone(why)
        self.assertEqual(s.said.splitlines()[:3], [
            "snippet.cpp:1:10: warning: code should be clang-formatted [-Wclang-format-violations]",
            "int lives     = 3;", "         ^"])

    def test_a_block_it_leaves_alone_is_red(self):
        why, _s = self.run_one(self.RIGHT, expect_gate="format")
        self.assertIn("is shown as refused by clang-format, and it says nothing", why)

    def test_the_right_way_has_to_be_formatted(self):
        self.assertIsNone(self.run_one(self.RIGHT, format_clean=True)[0])
        why, _s = self.run_one("int *score = nullptr;\nint* other = nullptr;", format_clean=True)
        self.assertIn("would change it", why)
        self.assertIn("snippet.cpp:2:4", why)

    def test_another_clang_format_is_refused(self):
        real = snippets._version_of
        snippets._version_of = lambda binary: "clang-format version 99.0.0"
        try:
            why, _s = self.run_one(self.RIGHT, format_clean=True)
        finally:
            snippets._version_of = real
        self.assertIn("is checked with clang-format", why)
        self.assertIn("FROZEN_VERSIONS.md", why)


class ShowSaidTest(unittest.TestCase):
    """The page shows what the tool said under the block, in a slot the build
    fills once the compile tier ran; until then, what the page can say."""

    def setUp(self):
        if not (FRAMEWORK / "include" / "rmp").is_dir():
            self.skipTest("no framework next to rmp-docs")

    BLOCKS = ('<pre data-lang="cpp" data-harness="function" data-expect="error" '
              'data-error="no matching function">rmp::ui::button(42);</pre>\n'
              '<pre data-lang="cpp" data-harness="toplevel" data-expect="lint" '
              'data-check="modernize-avoid-c-style-cast">int y = (int)1.5;</pre>\n'
              '<pre data-lang="cpp" data-harness="toplevel">int fine = 0;</pre>\n')

    def site(self):
        return StaticRuleTest.site_with(self, {"content/index.html": self.BLOCKS})

    def test_the_slot_is_filled_with_the_tools_words(self):
        site = self.site()
        site.snippets[0].said = "snippet.cpp:1:1: error: no matching function for call to 'button'"
        site.snippets[1].said = "snippet.cpp:1:9: warning: C-style casts are discouraged <here>"
        self.assertEqual(site.show_said(), [])
        out = site.outputs["index.html"]
        self.assertEqual(out.count('<pre class="compiler-output" data-lang="text" data-said>'), 2)
        self.assertIn("no matching function for call to &#x27;button&#x27;", out.replace("'", "&#x27;"))
        self.assertIn("discouraged &lt;here&gt;", out)
        self.assertNotIn("<!--said:", out)
        # The words the page typed are replaced by the compiler's own.
        self.assertNotIn("saying among other things", out)

    def test_before_the_compile_tier_the_page_says_what_it_can(self):
        out = self.site().outputs["index.html"]
        self.assertIn("saying among other things: <code>no matching function</code>", out)
        self.assertEqual(out.count("<!--said:"), 2)

    def test_a_refused_block_with_nothing_to_show_is_a_problem(self):
        site = self.site()
        site.snippets[0].said = "snippet.cpp:1:1: error: no matching function"
        problems = site.show_said()
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].line, site.snippets[1].line)

    def test_gates_without_rules(self):
        site = StaticRuleTest.site_with(self, {"content/index.html":
            '<pre data-lang="cpp" data-harness="header" data-expect="gate" data-gate="pointers">'
            "int x;</pre>\n"
            '<pre data-lang="cpp" data-harness="toplevel" data-expect="gate" data-gate="format">'
            "int x;</pre>\n"
            '<pre data-lang="cpp" data-harness="toplevel" data-expect="gate" data-gate="format" '
            'data-rule="F1">int x;</pre>\n'})
        body = next(p for p in site.pages if p.url == "index.html").body
        self.assertIn("Compiles; <code>rmp test pointers</code> refuses it<", body)
        self.assertIn("Compiles; <code>rmp test fmt</code> refuses it<", body)
        got = [str(p) for p in site.problems if p.gate == "snippets"]
        self.assertEqual(len(got), 1, got)
        self.assertIn("names no rule", got[0])

    def test_the_right_way_on_a_guidelines_page_is_held_to_clang_format(self):
        site = StaticRuleTest.site_with(self, {
            "content/index.html": '<pre data-lang="cpp" data-harness="toplevel">int x = 0;</pre>',
            "content/guidelines/index.html": '<pre data-lang="cpp" data-harness="toplevel">int x = 0;</pre>'})
        self.assertEqual({s.page: s.format_clean for s in site.snippets},
                         {"content/index.html": False, "content/guidelines/index.html": True})


class CompileTierTest(unittest.TestCase):
    """tools/build.py's compile tier, as `check` and `build` both run it: the
    blocks judged, their slots filled, and the style rules held -- all three,
    whether the site is written or not."""

    @classmethod
    def setUpClass(cls):
        LintTest.setUpClass()

    def test_check_and_build_run_all_of_it(self):
        import build
        site = StaticRuleTest.site_with(self, {"content/index.html":
            '<pre data-lang="cpp" data-harness="toplevel" data-expect="lint" '
            'data-check="modernize-avoid-c-style-cast">int half() { return (int)3.5; }</pre>\n'
            '<pre data-lang="cpp" data-harness="function">int n = 0;\nn++;</pre>\n'})
        problems = build.compile_tier(site)
        self.assertEqual([(p.gate, p.line) for p in problems],
                         [("snippets", site.snippets[1].line + 2)], [str(p) for p in problems])
        self.assertIn("S6", problems[0].message)
        out = site.outputs["index.html"]
        self.assertIn("[modernize-avoid-c-style-cast]", out)
        self.assertNotIn("<!--said:", out)


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


if __name__ == "__main__":
    unittest.main()
