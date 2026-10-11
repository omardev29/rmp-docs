"""The examples' pages: what examples.toml must say, and what is read from
the framework instead of typed."""

import sys
import tempfile
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import examples  # noqa: E402


FACTORY = ("void install_factory_actions() {\n"
           '    action("move_left", KEY_A, KEY_LEFT, GAMEPAD_BUTTON_LEFT_FACE_LEFT,\n'
           "           stick(GAMEPAD_AXIS_LEFT_X, -1));\n"
           '    action("move_right", KEY_D, KEY_RIGHT);\n'
           '    action("move_up", KEY_W);\n'
           '    action("move_down", KEY_S);\n'
           '    // action("ui_menu", KEY_M); is a comment, not an action\n'
           '    action("ui_cancel", KEY_ESCAPE, GAMEPAD_BUTTON_RIGHT_FACE_RIGHT);\n'
           "}\n")


def framework(tmp: Path, names, readme_rows, factory: str = FACTORY) -> Path:
    (tmp / "src" / "rmp").mkdir(parents=True)
    (tmp / "src" / "rmp" / "input.cpp").write_text(factory)
    (tmp / "examples").mkdir()
    for n in names:
        (tmp / "examples" / n / "src").mkdir(parents=True)
        (tmp / "examples" / n / "src" / "main.cpp").write_text(
            '// x\nvoid f() { rmp::input::action("jump", KEY_SPACE, GAMEPAD_BUTTON_RIGHT_FACE_DOWN);\n'
            "if (IsKeyPressed(KEY_R)) {} }\n")
    rows = "\n".join(f"| [{n.split('/')[-1]}]({n}/src/main.cpp) | {text} |" for n, text in readme_rows)
    (tmp / "examples" / "README.md").write_text(f"# Examples\n\n| | |\n|---|---|\n{rows}\n")
    return tmp


class LoadTest(unittest.TestCase):
    def test_every_disagreement_is_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = framework(Path(tmp), ["games/01_pong", "ui/01_menu", "ads/01_x"],
                           [("games/01_pong", "Pong."), ("ui/01_menu", "A menu.")])
            conf = {"examples": {"games/01_pong": {"play": True},
                                 "ads/01_x": {"play": False},
                                 "games/99_gone": {"play": True}}}
            got, problems = examples.load(fw, conf)
            said = "\n".join(problems)
            self.assertIn("examples/ui/01_menu has no entry in examples.toml", said)
            self.assertIn("ads/01_x is not played and does not say why", said)
            self.assertIn("names games/99_gone, which is not an example", said)
            self.assertIn("examples/ads/01_x has no row in examples/README.md", said)
            self.assertEqual(sorted(e.path for e in got), ["ads/01_x", "games/01_pong", "ui/01_menu"])

    def test_an_agreeing_tree_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = framework(Path(tmp), ["games/01_pong"], [("games/01_pong", "Pong.")])
            got, problems = examples.load(fw, {"examples": {"games/01_pong": {"play": True}}})
            self.assertEqual(problems, [])
            self.assertEqual(got[0].keys, [("jump", ["KEY_SPACE", "GAMEPAD_BUTTON_RIGHT_FACE_DOWN"]),
                                           ("", ["KEY_R"])])
            self.assertEqual((got[0].title, got[0].target, got[0].url),
                             ("Pong", "example_games_01_pong", "examples/games/01_pong.html"))

    def test_the_real_framework_and_examples_toml_agree(self):
        import os
        import tomllib
        fw = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))
        if not (fw / "examples").is_dir():
            self.skipTest("no framework next to rmp-docs")
        conf = tomllib.loads((DOCS / "examples.toml").read_text())
        _got, problems = examples.load(fw, conf)
        self.assertEqual(problems, [])


class KeysTest(unittest.TestCase):
    """The Keys table is read from the example's code: what it defines, what
    it reads by name of the actions that come defined, what it asks raylib."""

    def keys(self, code: str):
        with tempfile.TemporaryDirectory() as tmp:
            factory = examples.factory_actions(framework(Path(tmp), [], []))
        return examples.keys_of([("src/main.cpp", code)], factory)

    def test_the_framework_actions_are_read_from_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = examples.factory_actions(framework(Path(tmp), [], []))
        self.assertEqual(got["move_left"], ["KEY_A", "KEY_LEFT", "GAMEPAD_BUTTON_LEFT_FACE_LEFT"])
        self.assertEqual(got["ui_cancel"], ["KEY_ESCAPE", "GAMEPAD_BUTTON_RIGHT_FACE_RIGHT"])
        self.assertNotIn("ui_menu", got)

    def test_a_comment_is_not_a_key(self):
        code = ("// Through rmp::input rather than IsKeyPressed(KEY_ESCAPE).\n"
                '/* rmp::input::action("shout", KEY_X); */\n'
                'if (rmp::input::just_pressed("ui_cancel")) back();\n')
        self.assertEqual(self.keys(code), [("ui_cancel", ["KEY_ESCAPE", "GAMEPAD_BUTTON_RIGHT_FACE_RIGHT"])])

    def test_a_string_that_looks_like_a_comment_is_still_code(self):
        code = ('const char *url = "https://example.org";\n'
                "if (IsKeyPressed(KEY_R)) restart();\n")
        self.assertEqual(self.keys(code), [("", ["KEY_R"])])

    def test_actions_read_by_name_come_with_their_keys(self):
        code = ('x = rmp::input::axis("move_left", "move_right");\n'
                'if (rmp::input::pressed("ui_cancel")) back();\n'
                'if (rmp::input::just_released("never_defined")) {}\n')
        self.assertEqual(self.keys(code), [
            ("move_left", ["KEY_A", "KEY_LEFT", "GAMEPAD_BUTTON_LEFT_FACE_LEFT"]),
            ("move_right", ["KEY_D", "KEY_RIGHT"]),
            ("ui_cancel", ["KEY_ESCAPE", "GAMEPAD_BUTTON_RIGHT_FACE_RIGHT"])])

    def test_vector_and_axis_with_no_names_read_the_moves(self):
        self.assertEqual([a for a, _ in self.keys("v = rmp::input::vector();\n")],
                         ["move_left", "move_right", "move_up", "move_down"])
        self.assertEqual([a for a, _ in self.keys("x = rmp::input::axis();\n")],
                         ["move_left", "move_right"])

    def test_an_action_the_example_defines_is_its_own(self):
        code = ('rmp::input::action("move_up", KEY_I);\n'
                'if (rmp::input::pressed("move_up")) up();\n')
        self.assertEqual(self.keys(code), [("move_up", ["KEY_I"])])

    def test_a_framework_without_its_actions_is_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = framework(Path(tmp), ["games/01_pong"], [("games/01_pong", "Pong.")], factory="")
            _got, problems = examples.load(fw, {"examples": {"games/01_pong": {"play": True}}})
        self.assertEqual(len(problems), 1)
        self.assertIn("has no install_factory_actions()", problems[0])


class MarkdownTest(unittest.TestCase):
    def test_links_code_and_bold(self):
        got = examples.markdown_inline("**A [`x.py`](../tools/x.py) and [LDtk](https://ldtk.io).** `a<b>`",
                                       "https://github.com/o/r", "abc")
        self.assertEqual(got, '<strong>A <a href="https://github.com/o/r/tree/abc/tools/x.py"><code>x.py</code></a>'
                              ' and <a href="https://ldtk.io">LDtk</a>.</strong> <code>a&lt;b&gt;</code>')


if __name__ == "__main__":
    unittest.main()
