"""Tutorials: a real game made with rmp new, built and booted after every step."""

import os
import shutil
import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import project  # noqa: E402

FRAMEWORK = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))


class TomlEditTest(unittest.TestCase):
    BASE = '[project]\nname = "a"\n\n[window]\ntitle = "x"   # a comment\nwidth = 800\n\n[ui]\ntheme = "dark"\n'

    def test_a_key_is_replaced_where_it_is(self):
        got = project.set_toml_keys(self.BASE, '[window]\ntitle = "My Game"')
        self.assertIn('[window]\ntitle = "My Game"\nwidth = 800', got)
        self.assertEqual(got.count("title ="), 1)

    def test_a_key_is_added_to_its_section(self):
        got = project.set_toml_keys(self.BASE, "[window]\nvsync = false")
        self.assertIn("width = 800\nvsync = false\n\n[ui]", got)

    def test_a_section_is_added_at_the_end(self):
        got = project.set_toml_keys(self.BASE, "[audio]\nmusic = 0.5")
        self.assertTrue(got.rstrip().endswith("[audio]\nmusic = 0.5"))

    def test_a_line_that_is_not_a_key_is_refused(self):
        with self.assertRaises(ValueError):
            project.set_toml_keys(self.BASE, "[window]\nthis is prose")


class BuildTest(unittest.TestCase):
    """Slow: a whole game built for the software renderer. The site's CI runs
    it (RMP_DOCS_SLOW=1); a laptop skips it unless asked."""

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("RMP_DOCS_SLOW"):
            raise unittest.SkipTest("set RMP_DOCS_SLOW=1 to build a game here")
        if shutil.which("cmake") is None or not (FRAMEWORK / "tools" / "rmp.py").is_file():
            raise unittest.SkipTest("needs cmake and the framework")

    def test_a_step_that_breaks_the_game_is_red_and_the_ones_before_are_green(self):
        good = project.Step("content/one.html", [project.ProjectFile(
            "content/one.html", 1, "raylib_multiplatform.toml", '[window]\ntitle = "Step one"', "toml")])
        bad = project.Step("content/two.html", [project.ProjectFile(
            "content/two.html", 1, "src/scenes/main_menu.cpp", "this is not C++", "cpp")])
        results = project.run(FRAMEWORK, "tutorial_check", [good, bad])
        self.assertEqual(results[0], (good, None))
        self.assertIs(results[1][0], bad)
        self.assertIn("does not build and boot after this page", results[1][1])


class RelativeFrameworkTest(unittest.TestCase):
    """CI names the framework relative to the docs (RMP_FRAMEWORK=framework),
    and `rmp new` runs in a temporary folder: a path left relative pointed at
    a framework inside that folder, and every tutorial failed before its first
    page."""

    def test_rmp_new_works_from_a_relative_framework_path(self):
        if not (FRAMEWORK / "tools" / "rmp.py").is_file():
            self.skipTest("no framework next to rmp-docs")
        relative = Path(os.path.relpath(FRAMEWORK.resolve(), Path.cwd()))
        self.assertFalse(relative.is_absolute())
        self.assertEqual(project.run(relative, "relative_check", []), [])


if __name__ == "__main__":
    unittest.main()
