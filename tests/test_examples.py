"""The examples' pages: what examples.toml must say, and what is read from
the framework instead of typed."""

import sys
import tempfile
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import examples  # noqa: E402


def framework(tmp: Path, names, readme_rows) -> Path:
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
        import tomllib
        fw = DOCS.parent / "raylib_multiplatform"
        if not (fw / "examples").is_dir():
            self.skipTest("no framework next to rmp-docs")
        conf = tomllib.loads((DOCS / "examples.toml").read_text())
        _got, problems = examples.load(fw, conf)
        self.assertEqual(problems, [])


class MarkdownTest(unittest.TestCase):
    def test_links_code_and_bold(self):
        got = examples.markdown_inline("**A [`x.py`](../tools/x.py) and [LDtk](https://ldtk.io).** `a<b>`",
                                       "https://github.com/o/r", "abc")
        self.assertEqual(got, '<strong>A <a href="https://github.com/o/r/tree/abc/tools/x.py"><code>x.py</code></a>'
                              ' and <a href="https://ldtk.io">LDtk</a>.</strong> <code>a&lt;b&gt;</code>')


if __name__ == "__main__":
    unittest.main()
