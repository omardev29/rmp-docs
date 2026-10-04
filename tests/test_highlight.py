"""The highlighter changes colours, never text: what comes out of a block is
exactly what went in, in every language, and the token classes land where a
reader expects them."""

import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs.highlight import LANGS, highlight, plain  # noqa: E402

SAMPLES = {
    "cpp": '#include <rmp/scene.h> // a comment\nclass A : public rmp::Scene {\n'
           '    void _draw() override { if (x > 0.5f) rmp::ui::text("a \\"q\\" <b>"); }\n'
           '    static constexpr int MAX = 0x1F; [[nodiscard]] float y = 1e-3f;\n};\n'
           'auto s = R"(raw ( "string" ))"; char c = \'\\n\';\n/* block\n comment */',
    "c": '#define RMP_X 1\nint main(void) { return RMP_X; }',
    "toml": '[window]  # the window\nwidth = 800\ntitle = "My \\"Game\\""\nvsync = true\n[[a.b]]\nx = 1.5e3',
    "shell": 'rmp new "my game" && cd my_game   # go\nexport PATH="$HOME/x:${PATH}"\nif [ -f a ]; then echo \'b\'; fi',
    "powershell": '$x = [Environment]::GetEnvironmentVariable("Path", "User") # c\nSet-ExecutionPolicy -Scope CurrentUser',
    "cmake": 'add_library(rmp STATIC ${SOURCES}) # c\nset(X "a;b")',
    "json": '{"a": [1, 2.5, true, null], "b": "c"}',
    "yaml": 'jobs:\n  lint:\n    runs-on: ubuntu-24.04 # c\n    if: ${{ inputs.x }}',
    "text": "  a <b> & c",
}


class HighlightTest(unittest.TestCase):
    def test_every_language_has_a_sample(self):
        self.assertEqual(sorted(SAMPLES), sorted(LANGS))

    def test_the_text_survives_exactly(self):
        for lang, src in SAMPLES.items():
            with self.subTest(lang=lang):
                self.assertEqual(plain(highlight(src, lang)), src)

    def test_the_classes_land_where_they_should(self):
        h = highlight(SAMPLES["cpp"], "cpp")
        for piece in ('<span class="k">class</span>', '<span class="k">override</span>',
                      '<span class="p">#include</span>', '<span class="s">&lt;rmp/scene.h&gt;</span>',
                      '<span class="c">// a comment</span>', '<span class="f">_draw</span>',
                      '<span class="m">MAX</span>', '<span class="n">0x1F</span>',
                      '<span class="a">[[nodiscard]]</span>', '<span class="t">Scene</span>'):
            self.assertIn(piece, h)
        self.assertIn('<span class="a">width</span>', highlight(SAMPLES["toml"], "toml"))
        self.assertIn('<span class="f">rmp</span>', highlight(SAMPLES["shell"], "shell"))

    def test_an_unknown_language_is_an_error(self):
        with self.assertRaises(ValueError):
            highlight("x", "rust")


if __name__ == "__main__":
    unittest.main()
