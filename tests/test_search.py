"""Search: Python indexes and JavaScript searches with the same tokenizer."""

import re
import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import search  # noqa: E402


class TokenizerTest(unittest.TestCase):
    def test_python_and_javascript_split_the_same_way(self):
        js = (DOCS / "assets" / "js" / "search.js").read_text()
        m = re.search(r"function tokens\(text\) \{ return \(text\.toLowerCase\(\)\.match\(/(.+?)/g\)", js)
        self.assertIsNotNone(m, "search.js no longer has the tokens() this test reads")
        self.assertEqual(m.group(1), search.TOKEN.pattern)

    def test_names_and_prose_meet(self):
        self.assertEqual(search.tokens("rmp::ui::button"), ["rmp", "ui", "button"])
        self.assertEqual(search.tokens("updates_below"), ["updates", "below"])
        self.assertEqual(search.tokens("Updates below"), ["updates", "below"])


if __name__ == "__main__":
    unittest.main()
