"""Pages made from the framework's own files: what they promise has to be
something the framework really does."""

import sys
import tempfile
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import generated  # noqa: E402


class BuildDefinesTest(unittest.TestCase):
    """reference.toml [build_defines] lists macros the build passes. One that
    no build passes any more would be read as 0 by every #if a reader writes."""

    def framework(self, cmake: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "CMakeLists.txt").write_text(cmake)
        return tmp

    def test_a_define_the_build_passes_is_documented(self):
        fw = self.framework('target_compile_definitions(rmp PUBLIC RMP_PRODUCTION_BUILD=1)\n')
        table, wrong = generated.build_defines_table(
            fw, {"build_defines": {"RMP_PRODUCTION_BUILD": {"set_in": ["CMakeLists.txt"], "doc": "1 or 0."}}})
        self.assertEqual(wrong, [])
        self.assertIn('id="RMP_PRODUCTION_BUILD"', table)

    def test_a_define_no_build_passes_is_refused(self):
        fw = self.framework('# RMP_PRODUCTION_BUILD is only mentioned here\n')
        _table, wrong = generated.build_defines_table(
            fw, {"build_defines": {"RMP_PRODUCTION_BUILD": {"set_in": ["CMakeLists.txt", "missing.yml"],
                                                            "doc": "1 or 0."}}})
        self.assertEqual(len(wrong), 2)
        self.assertIn("CMakeLists.txt does not set it", wrong[0])
        self.assertIn("missing.yml does not set it", wrong[1])

    def test_a_define_that_names_no_file_is_refused(self):
        _table, wrong = generated.build_defines_table(
            self.framework(""), {"build_defines": {"RMP_X": {"doc": "?"}}})
        self.assertEqual(wrong, ["[build_defines] RMP_X: says no file that sets it (set_in)"])

    def test_the_real_ones_hold(self):
        import os
        fw = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))
        if not (fw / "CMakeLists.txt").is_file():
            self.skipTest("no framework next to rmp-docs")
        import tomllib
        refconf = tomllib.loads((DOCS / "reference.toml").read_text())
        _table, wrong = generated.build_defines_table(fw, refconf)
        self.assertEqual(wrong, [])
        self.assertTrue(refconf["build_defines"])


class BuildSwitchesTest(unittest.TestCase):
    """reference.toml [build_switches]: RMP_ names the build reads that are not
    macros -- a CMake option, an environment variable. Each is held to the
    files it says read it, by the shape its kind has there: a comment that
    only mentions the name is not a build that reads it."""

    def framework(self, **files) -> Path:
        tmp = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (tmp / name.replace("__", "/")).parent.mkdir(parents=True, exist_ok=True)
            (tmp / name.replace("__", "/")).write_text(text)
        return tmp

    def one(self, fw, name, kind, read_in):
        return generated.build_switches_table(
            fw, {"build_switches": {name: {"kind": kind, "read_in": read_in, "doc": "It does."}}})

    def test_an_option_cmake_reads_is_documented(self):
        fw = self.framework(**{"CMakeLists.txt": 'option(RMP_WERROR "Warnings are errors" OFF)\n'})
        table, wrong = self.one(fw, "RMP_WERROR", "cmake option", ["CMakeLists.txt"])
        self.assertEqual(wrong, [])
        self.assertIn('id="RMP_WERROR"', table)
        self.assertIn("a CMake option", table)

    def test_an_environment_variable_cmake_reads_is_documented(self):
        fw = self.framework(**{"cmake__x.cmake": 'if("$ENV{RMP_REQUIRE_X}" STREQUAL "1")\nendif()\n'})
        _table, wrong = self.one(fw, "RMP_REQUIRE_X", "environment", ["cmake/x.cmake"])
        self.assertEqual(wrong, [])

    def test_a_name_only_mentioned_is_red(self):
        fw = self.framework(**{"CMakeLists.txt": "# RMP_WERROR turns them into errors\n"})
        _table, wrong = self.one(fw, "RMP_WERROR", "cmake option", ["CMakeLists.txt", "gone.cmake"])
        self.assertEqual(wrong, ["[build_switches] RMP_WERROR: CMakeLists.txt does not read it as a CMake option",
                                 "[build_switches] RMP_WERROR: gone.cmake does not read it as a CMake option"])

    def test_the_wrong_kind_is_red(self):
        fw = self.framework(**{"CMakeLists.txt": 'option(RMP_WERROR "x" OFF)\n'})
        _table, wrong = self.one(fw, "RMP_WERROR", "environment", ["CMakeLists.txt"])
        self.assertEqual(wrong, ["[build_switches] RMP_WERROR: CMakeLists.txt does not read it as an "
                                 "environment variable"])
        _table, wrong = self.one(fw, "RMP_WERROR", "flag", ["CMakeLists.txt"])
        self.assertIn("kind is 'flag'", wrong[0])

    def test_a_switch_that_names_no_file_is_red(self):
        _table, wrong = self.one(self.framework(), "RMP_X", "cmake option", [])
        self.assertEqual(wrong, ["[build_switches] RMP_X: says no file that reads it (read_in)"])

    def test_the_real_ones_hold(self):
        import os
        import tomllib
        fw = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))
        if not (fw / "CMakeLists.txt").is_file():
            self.skipTest("no framework next to rmp-docs")
        refconf = tomllib.loads((DOCS / "reference.toml").read_text())
        _table, wrong = generated.build_switches_table(fw, refconf)
        self.assertEqual(wrong, [])
        self.assertTrue(refconf["build_switches"])


class ConfigSeeTest(unittest.TestCase):
    """reference.toml [config_see]: a key the configuration reference links to
    the page that explains it further. One for a key the .toml does not have
    is red, like every decision in reference.toml about a name that is gone."""

    ROWS = [{"key": "dev.sanitize", "comment": "What a Debug build is instrumented with."}]

    def test_an_entry_is_a_link_under_its_key(self):
        see, wrong = generated.config_see(self.ROWS, {"config_see": {"dev.sanitize": {
            "href": "/manual/basics/configuration.html#sanitizers", "says": "what it catches"}}})
        self.assertEqual(wrong, [])
        self.assertEqual(see, {"dev.sanitize": ("/manual/basics/configuration.html#sanitizers",
                                                "what it catches")})

    def test_a_key_the_toml_does_not_have_is_red(self):
        _see, wrong = generated.config_see(self.ROWS, {"config_see": {"dev.sanitise": {
            "href": "/x.html", "says": "y"}}})
        self.assertEqual(wrong, ['[config_see."dev.sanitise"]: the .toml has no key dev.sanitise'])

    def test_an_entry_says_where_and_what(self):
        for spec in ({"href": "https://example.com/", "says": "y"}, {"href": "/x.html", "says": " "},
                     "/x.html"):
            with self.subTest(spec=spec):
                _see, wrong = generated.config_see(self.ROWS, {"config_see": {"dev.sanitize": spec}})
                self.assertEqual(len(wrong), 1)
                self.assertIn("an href inside the site", wrong[0])


class ConfigCommentTest(unittest.TestCase):
    """reference.toml [config_comment]: the configuration reference shows the
    framework's comment for every key, and an entry here replaces one that is
    not true of the framework yet -- only while that comment is the one it was
    written against."""

    ROWS = [{"key": "android.gradle_offline", "comment": "Where CI's Android job gets Gradle. More."}]

    def rows(self):
        return [dict(r) for r in self.ROWS]

    def test_an_entry_replaces_the_comment(self):
        rows = self.rows()
        wrong = generated.config_comments(rows, {"config_comment": {"android.gradle_offline": {
            "replaces": "Where CI's Android job", "comment": "What it does.", "reason": "r"}}})
        self.assertEqual(wrong, [])
        self.assertEqual(rows[0]["comment"], "What it does.")

    def test_a_comment_that_changed_is_red_and_shown_as_it_is(self):
        rows = self.rows()
        wrong = generated.config_comments(rows, {"config_comment": {"android.gradle_offline": {
            "replaces": "Whether the Android job", "comment": "What it does.", "reason": "r"}}})
        self.assertEqual(len(wrong), 1)
        self.assertIn("no longer starts with", wrong[0])
        self.assertIn("Where CI's Android job gets Gradle. More.", wrong[0])
        self.assertEqual(rows[0]["comment"], self.ROWS[0]["comment"])

    def test_a_key_the_toml_does_not_have_is_red(self):
        wrong = generated.config_comments(self.rows(), {"config_comment": {"android.nothing": {
            "replaces": "x", "comment": "y", "reason": "z"}}})
        self.assertEqual(wrong, ['[config_comment."android.nothing"]: the .toml has no key android.nothing'])

    def test_an_entry_says_what_and_why(self):
        wrong = generated.config_comments(self.rows(), {"config_comment": {
            "android.gradle_offline": {"replaces": "Where", "comment": " "}}})
        self.assertEqual(wrong, ['[config_comment."android.gradle_offline"]: no comment, reason'])

    def test_the_real_ones_hold(self):
        import os
        import tomllib
        fw = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))
        if not (fw / "tools" / "configure.py").is_file():
            self.skipTest("no framework next to rmp-docs")
        rows = generated.run_json(fw, "tools/configure.py", "--print-schema")
        refconf = tomllib.loads((DOCS / "reference.toml").read_text())
        self.assertEqual(generated.config_comments(rows, refconf), [])


if __name__ == "__main__":
    unittest.main()
