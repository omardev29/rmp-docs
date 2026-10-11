"""The flags gate: every flag between the framework's BEGIN/END markers is on
the Security page.

Each test starts from tests/fixtures/gates/flags/good -- a framework in the
shape the real one writes its blocks, and a page that lists every flag -- and
changes one thing: a flag planted in a block, a flag taken off the page, a
marker removed, doubled or reversed. Each of those has to be red, and name
what it is about. The last class reads the real framework, when there is one.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import checks, flags  # noqa: E402

GOOD = DOCS / "tests" / "fixtures" / "gates" / "flags" / "good"
FRAMEWORK = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))


def wanted(text: str) -> list[str]:
    return [w.flag for w in flags.read_block("x", text).wants]


class ReadTest(unittest.TestCase):
    """What a block can emit, read as CMake reads it."""

    def block(self, body: str) -> str:
        return f"{flags.BEGIN}\n{body}\n{flags.END}\n"

    def test_comments_messages_and_brackets_are_not_flags(self):
        text = self.block("# -fin-a-comment\n"
                          "message(STATUS \"-fin-a-message\")\n"
                          "file(WRITE x [=[ -fin-a-bracket ]=])\n"
                          "list(APPEND RMP_RELEASE_C_FLAGS -freal)  # -fafter-it")
        self.assertEqual(wanted(text), ["-freal"])

    def test_only_what_is_between_the_markers(self):
        text = "add_compile_options(-fbefore)\n" + self.block("set(X -finside)") + \
               "add_compile_options(-fafter)\n"
        self.assertEqual(wanted(text), ["-finside"])

    def test_every_kind_of_flag(self):
        text = self.block("set(F -fone -Wall -Wl,-z,relro -U_X -DY=1 /GS /INCREMENTAL:NO)")
        self.assertEqual(wanted(text), ["-fone", "-Wall", "-Wl,-z,relro", "-U_X", "-DY=1", "/GS",
                                        "/INCREMENTAL:NO"])

    def test_a_define_is_a_flag_and_a_generator_expression_is_unwrapped(self):
        text = self.block("target_compile_definitions(${target} PRIVATE\n"
                          "  $<$<COMPILE_LANGUAGE:CXX>:_GLIBCXX_ASSERTIONS> RMP_SANITIZE=1)\n"
                          "target_compile_options(${t} PRIVATE $<$<COMPILE_LANGUAGE:C>:-fpattern>)")
        self.assertEqual(wanted(text), ["-D_GLIBCXX_ASSERTIONS", "-DRMP_SANITIZE=1", "-fpattern"])

    def test_a_path_or_a_variable_is_not_a_flag(self):
        text = self.block('set(X "${CMAKE_CURRENT_LIST_DIR}/hooks.c" RMP_LD${_flag} a-b-c)')
        self.assertEqual(wanted(text), [])

    def test_a_variable_in_a_flag_holds_what_the_block_gives_it(self):
        text = self.block("set(_level 3)\nset(_level 2)\n"
                          "list(APPEND F -D_FORTIFY_SOURCE=${_level})\n"
                          "set(_list ${names})\nlist(APPEND _list float-cast-overflow)\n"
                          'list(JOIN _list "," _joined)\nset(C -fsanitize=${_joined})\n'
                          'set(L "-fsanitize-ignorelist=${OUTSIDE}")')
        got = {w.flag: (w.prefix, w.values) for w in flags.read_block("x", text).wants}
        self.assertEqual(got["-D_FORTIFY_SOURCE=${_level}"], ("-D_FORTIFY_SOURCE=", ["2", "3"]))
        self.assertEqual(got["-fsanitize=${_joined}"], ("-fsanitize=", ["float-cast-overflow"]))
        self.assertEqual(got["-fsanitize-ignorelist=${OUTSIDE}"], ("-fsanitize-ignorelist=", []))

    def test_pie_is_keyed_on_its_option(self):
        text = self.block('option(RMP_RELEASE_PIE "PIE" ON)')
        block = flags.read_block("x", text)
        self.assertEqual([w.flag for w in block.wants], ["-fPIE", "-pie"])
        self.assertEqual([name for _line, name in block.options], ["RMP_RELEASE_PIE"])


class GateTest(unittest.TestCase):
    """The good fixture, and one thing changed at a time."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(GOOD, self.root, dirs_exist_ok=True)
        self.cmake = self.root / "framework" / "CMakeLists.txt"
        self.sanitize = self.root / "framework" / "cmake" / "sanitize.cmake"
        self.page = self.root / "content" / "framework" / "security.html"

    def problems(self) -> list[str]:
        return [str(p) for p in flags.check_flags(checks.Context.from_folder(self.root))]

    def edit(self, path: Path, old: str, new: str, count: int = 1):
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, count))

    def assertRedWith(self, *pieces):
        got = self.problems()
        self.assertTrue(got, "the gate passed")
        said = "\n".join(got)
        for piece in pieces:
            self.assertIn(piece, said)

    def test_the_good_fixture_is_green(self):
        self.assertEqual(self.problems(), [])

    def test_a_flag_planted_in_a_block_is_red_and_named(self):
        """The red this gate was written for: a flag added to the framework
        with no paragraph for it."""
        planted = {
            self.cmake: ("list(APPEND RMP_RELEASE_C_FLAGS -fcf-protection)\n",
                         "`-fcf-protection` is a flag CMakeLists.txt can give a build"),
            self.sanitize: ("function(x target)\n  target_compile_definitions(${target} PRIVATE "
                            "RMP_SANITIZE_THREAD=1)\nendfunction()\n",
                            "`-DRMP_SANITIZE_THREAD=1` is a flag cmake/sanitize.cmake can give"),
        }
        for path, (added, said) in planted.items():
            with self.subTest(file=path.name):
                original = path.read_text()
                self.edit(path, flags.END, added + flags.END)
                self.assertRedWith(said)
                # The same statement after END is not the page's business.
                path.write_text(original.replace(flags.END + "\n", flags.END + "\n" + added))
                self.assertEqual(self.problems(), [])
                path.write_text(original)

    def test_a_value_planted_in_a_flag_is_red(self):
        self.edit(self.sanitize, "list(APPEND _list float-cast-overflow)",
                  "list(APPEND _list float-cast-overflow nullability)")
        self.assertRedWith("`-fsanitize=` with `nullability`")
        self.edit(self.cmake, "set(_level 2)", "set(_level 2)\n    set(_level 1)")
        self.assertRedWith("`-D_FORTIFY_SOURCE=` with `1`")

    def test_a_planted_option_is_red(self):
        self.edit(self.cmake, flags.END, 'option(RMP_RELEASE_CFI "control flow" OFF)\n' + flags.END)
        self.assertRedWith("`RMP_RELEASE_CFI` is an option CMakeLists.txt declares")

    def test_a_flag_removed_from_the_page_is_red_and_named(self):
        removed = {
            "<code>-fstack-protector-strong</code>": "`-fstack-protector-strong` is a flag",
            "<code>-Wl,-z,now</code>": "`-Wl,-z,now` is a flag",
            "<code>-pie</code>": "`-pie` is a flag",
            "<code>_GLIBCXX_ASSERTIONS</code>": "`-D_GLIBCXX_ASSERTIONS` is a flag",
            "<code>_FORTIFY_SOURCE=2</code>": "`-D_FORTIFY_SOURCE=` with `2`",
            "/fsanitize=address ": "`/fsanitize=address` is a flag",
            "-DRMP_SANITIZE=1\n": "`-DRMP_SANITIZE=1` is a flag",
            ",float-cast-overflow": "`-fsanitize=` with `float-cast-overflow`",
            "-fsanitize-ignorelist=cmake/sanitize_ignore.txt": "`-fsanitize-ignorelist=…`",
            "<code>-DRMP_RELEASE_PIE=OFF</code>": "`RMP_RELEASE_PIE` is an option",
        }
        original = self.page.read_text()
        for gone, said in removed.items():
            with self.subTest(removed=gone):
                self.edit(self.page, gone, "")
                self.assertRedWith(said)
                self.page.write_text(original)

    def test_a_flag_in_prose_is_not_written_as_code(self):
        self.edit(self.page, "<code>-Wl,-z,now</code>", "-Wl,-z,now")
        self.assertRedWith("`-Wl,-z,now` is a flag")

    def test_a_longer_flag_does_not_stand_for_a_shorter_one(self):
        self.edit(self.page, "<code>-Wl,-z,now</code>", "<code>-Wl,-z,nowhere</code>")
        self.assertRedWith("`-Wl,-z,now` is a flag")

    def test_markers_missing_doubled_reversed_or_misspelled_are_red(self):
        text = self.cmake.read_text()
        begin, end = flags.BEGIN + "\n", flags.END + "\n"
        broken = {
            "no begin": (text.replace(begin, ""), "has 0 BEGIN and 1 END"),
            "no end": (text.replace(end, ""), "has 1 BEGIN and 0 END"),
            "neither": (text.replace(begin, "").replace(end, ""), "has no `# BEGIN"),
            "misspelled": (text.replace(begin, begin.replace("security", "securty"))
                           .replace(end, end.replace("security", "securty")), "has no `# BEGIN"),
            "two pairs": (text + begin + end, "has 2 BEGIN and 2 END"),
            "reversed": (text.replace(begin, "@@").replace(end, begin).replace("@@", end),
                         "comes before BEGIN"),
        }
        for label, (variant, said) in broken.items():
            with self.subTest(variant=label):
                self.cmake.write_text(variant)
                self.assertRedWith("CMakeLists.txt (framework)", said)
        self.cmake.write_text(text)
        self.sanitize.write_text(self.sanitize.read_text().replace(begin, "").replace(end, ""))
        self.assertRedWith("cmake/sanitize.cmake (framework)", "has no `# BEGIN")

    def test_another_cmake_file_with_markers_is_read_too(self):
        (self.root / "framework" / "cmake" / "more.cmake").write_text(
            f"{flags.BEGIN}\nset(RMP_X -fmore)\n{flags.END}\n")
        self.assertRedWith("`-fmore` is a flag cmake/more.cmake can give a build")

    def test_no_page_is_red(self):
        self.page.unlink()
        self.assertRedWith("content/framework/security.html: is not there", "-fstack-protector-strong")


class RealFrameworkTest(unittest.TestCase):
    """The framework checkout this run points at, read as the gate reads it."""

    # A few of what the blocks give today, so that a reader that stopped
    # finding flags cannot pass by finding none -- the same list the
    # framework's SecurityPageMarkersTest keeps.
    SOME = {
        "CMakeLists.txt": ("-fstack-protector-strong", "-fstack-clash-protection",
                           "-D_FORTIFY_SOURCE=", "-U_FORTIFY_SOURCE", "-D_GLIBCXX_ASSERTIONS",
                           "-Wl,-z,relro", "-Wl,--dynamicbase", "-fPIE", "-pie"),
        "cmake/sanitize.cmake": ("-fsanitize=", "/fsanitize=address", "/INCREMENTAL:NO",
                                 "-fno-sanitize=vptr", "-ftrivial-auto-var-init=pattern",
                                 "-D_GLIBCXX_ASSERTIONS", "-DRMP_SANITIZE=1"),
    }

    def setUp(self):
        if not (FRAMEWORK / "CMakeLists.txt").is_file():
            self.skipTest("no framework checkout: set RMP_FRAMEWORK")
        if flags.BEGIN not in (FRAMEWORK / "CMakeLists.txt").read_text():
            self.skipTest("this framework has no Security markers yet")

    def test_the_blocks_yield_the_flags_they_hold(self):
        for rel, some in self.SOME.items():
            with self.subTest(file=rel):
                block = flags.read_block(rel, (FRAMEWORK / rel).read_text())
                self.assertEqual(block.wrong, [])
                got = [w.flag for w in block.wants]
                for flag in some:
                    self.assertTrue(any(g.startswith(flag) for g in got), f"{flag} not in {got}")

    def test_the_page_lists_every_flag_of_this_framework(self):
        page = DOCS / flags.PAGE
        if not page.is_file():
            self.skipTest("no Security page in this tree")
        ctx = checks.Context(docs=DOCS, framework=FRAMEWORK.resolve(),
                             sources={flags.PAGE: page.read_text(encoding="utf-8")})
        self.assertEqual([str(p) for p in flags.check_flags(ctx)], [])


if __name__ == "__main__":
    unittest.main()
