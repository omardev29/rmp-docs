"""The pictures a page shows (tools/rmpdocs/shots.py): which addresses are
shots, which framework file an e2e shot is, which pages a tutorial has a
picture for, and why an address is refused."""

import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import shots  # noqa: E402


def goldens(*present):
    def read(path):
        if path not in present:
            raise LookupError(path)
        return b"png"
    return read


class AddressTest(unittest.TestCase):
    def test_a_shot_is_an_address_from_the_root_under_shots(self):
        self.assertEqual(shots.site_path("/shots/e2e/ui/a/b.png"), "shots/e2e/ui/a/b.png")
        self.assertEqual(shots.site_path("/shots/e2e/ui/a/b.png?x#y"), "shots/e2e/ui/a/b.png")
        self.assertIsNone(shots.site_path("shots/e2e/ui/a/b.png"))
        self.assertIsNone(shots.site_path("/assets/a.png"))
        self.assertIsNone(shots.site_path(""))

    def test_an_e2e_shot_is_the_golden_of_the_same_name(self):
        self.assertEqual(shots.golden_of("shots/e2e/ui/04_settings/applied.png"),
                         "tests/e2e/golden/ui/04_settings/applied.png")

    def test_a_tutorial_shot_is_named_after_its_page(self):
        self.assertEqual(shots.tutorial_shot("my_game", "content/getting-started/a-player.html"),
                         "shots/tutorial/my_game/a-player.png")

    def test_the_steps_are_the_pages_that_write_files_of_a_project(self):
        sources = {"content/a/one.html": '<pre data-project="my_game" data-file="x">',
                   "content/a/two.html": "<p>no files</p>",
                   "content/b/three.html": "<pre data-project='other' data-file='y'>"}
        self.assertEqual(shots.tutorial_steps(sources), {("my_game", "one"), ("other", "three")})


class WhyNotTest(unittest.TestCase):
    STEPS = {("my_game", "a-player")}

    def why(self, src, *present):
        return shots.why_not(src, goldens(*present), self.STEPS)

    def test_a_golden_that_exists_and_a_tutorial_page_that_exists_are_shown(self):
        self.assertIsNone(self.why("/shots/e2e/ui/01_menu/options.png",
                                   "tests/e2e/golden/ui/01_menu/options.png"))
        self.assertIsNone(self.why("/shots/tutorial/my_game/a-player.png"))

    def test_a_picture_kept_beside_the_page_is_refused(self):
        self.assertIn("a screenshot taken by hand goes stale", self.why("shot.png"))
        self.assertIn("a raster image in a page", self.why("/assets/a.png"))

    def test_a_golden_no_script_takes_is_refused(self):
        self.assertIn("no e2e script takes that shot", self.why("/shots/e2e/ui/01_menu/gone.png"))

    def test_a_page_the_tutorial_does_not_have_is_refused(self):
        self.assertIn("no page called nowhere.html", self.why("/shots/tutorial/my_game/nowhere.png"))
        self.assertIn("of the tutorial 'other'", self.why("/shots/tutorial/other/a-player.png"))

    def test_an_address_of_the_wrong_shape_is_refused(self):
        for src in ("/shots/e2e/ui/../01_menu/options.png", "/shots/e2e/ui/01_menu/options.jpg",
                    "/shots/e2e/ui/options.png", "/shots/e2e/ui/a/b/c.png",
                    "/shots/tutorial/my_game.png", "/shots/other/a/b.png",
                    "/shots/e2e/ui/01 menu/options.png"):
            with self.subTest(src=src):
                self.assertIn("not an address of a shot", self.why(src, shots.golden_of(src[1:])))


class SceneTest(unittest.TestCase):
    HEADERS = {"my_game": {"scenes/game.h", "scenes/main_menu.h"}}
    SRC = "/shots/tutorial/my_game/a-player.png"

    def why(self, scene, header, src=SRC):
        return shots.why_not_scene(src, scene, header, self.HEADERS)

    def test_the_headers_are_the_ones_a_tutorial_writes_below_src(self):
        sources = {"content/a.html": '<pre data-lang="cpp" data-project="my_game" '
                                     'data-file="src/scenes/game.h">\n</pre>'
                                     '<pre data-project="my_game" data-file="src/scenes/game.cpp">',
                   "content/b.html": "<pre data-file='src/objects/coin.h' data-project='my_game'>"}
        self.assertEqual(shots.project_headers(sources),
                         {"my_game": {"scenes/game.h", "objects/coin.h"}})

    def test_a_scene_the_tutorial_wrote_starts_the_picture(self):
        self.assertIsNone(self.why("GameScene", "scenes/game.h"))
        self.assertIsNone(self.why("", ""))

    def test_the_two_go_together_and_only_on_a_tutorial_picture(self):
        self.assertIn("go together", self.why("GameScene", ""))
        self.assertIn("go together", self.why("", "scenes/game.h"))
        self.assertIn("and this is none", self.why("GameScene", "scenes/game.h",
                                                   "/shots/e2e/ui/a/b.png"))

    def test_a_scene_that_is_no_class_or_a_header_not_written_is_refused(self):
        self.assertIn("is not the name of a class", self.why("game_scene; int x", "scenes/game.h"))
        self.assertIn("no header the tutorial", self.why("GameScene", "scenes/pause.h"))
        self.assertIn("no header the tutorial", self.why("GameScene", "../scenes/game.h"))

    def test_main_starts_in_the_scene_named(self):
        main = '#include <rmp/app.h>\n\n#include "scenes/main_menu.h"\n\nRMP_GAME(MainMenuScene);\n'
        got = shots.start_in(main, "GameScene", "scenes/game.h")
        self.assertTrue(got.startswith('#include "scenes/game.h"\n'))
        self.assertIn("RMP_GAME(GameScene);", got)
        self.assertNotIn("RMP_GAME(MainMenuScene)", got)
        with self.assertRaises(ValueError):
            shots.start_in("int main() {}\n", "GameScene", "scenes/game.h")


if __name__ == "__main__":
    unittest.main()
