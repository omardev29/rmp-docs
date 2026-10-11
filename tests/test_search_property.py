"""tools/rmpdocs/search.py held to its promises for ANY page.

  tokens()        runs of [a-z0-9] after lowering, nothing else, and a text
                  split anywhere at a space is the two texts' tokens.
  visible_text()  what a reader sees of a page the site wrote: the text of
                  every element, unescaped, with the whitespace collapsed --
                  never a tag, never the inside of a script or a style.
  build()         JSON that reads back, and every word of a page's title,
                  headings and text in the index under that page.

Every property here was seen red: the commit that added this file says how.
A counterexample becomes a named case in tests/test_counterexamples.py.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hypothesis_profiles  # noqa: E402,F401  (first: the profile, or the skip)
from hypothesis import given, strategies as st  # noqa: E402
from under_test import load  # noqa: E402

search = load("search")
dom = load("dom")

WORDY = st.sampled_from(list("aZ09_:-. \n\t &<>;'\"") + [
    "rmp::ui::button", "updates_below", "İ", "ß", "K", "Σ", "ﬁ", "Ⅻ", "²", "&amp;", "the", "of"])
TEXT = st.lists(st.one_of(WORDY, st.characters(exclude_categories=("Cs",))), max_size=30).map("".join)


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# A page as the site writes it: elements and escaped text -- with, now and
# then, a script, a style or an svg, whose inside the index skips.
HIDDEN = st.sampled_from(["script", "style", "svg"])
BLOCK = st.recursive(
    TEXT.filter(bool).map(lambda t: ("text", t)),
    lambda kids: st.tuples(st.sampled_from(["p", "div", "span", "a", "code", "li", "h2"]),
                           st.lists(kids, max_size=4)).map(lambda t: ("el",) + t),
    max_leaves=10)
PAGE = st.lists(st.one_of(BLOCK, BLOCK, st.tuples(HIDDEN, TEXT.filter(
    lambda t: "</" not in t.lower())).map(lambda t: ("hidden",) + t)), max_size=5)


def page_markup(blocks) -> tuple[str, list[str]]:
    """The markup the site would write, and the text a reader sees, piece
    by piece."""
    out, seen = [], []

    def walk(node, parent=None):
        if node[0] == "text":
            parent.append(dom.Text(node[1]))
            seen.append(node[1])
            return
        seen.append(" ")          # a tag is a space between words
        if node[0] == "hidden":
            element = dom.el(node[1])
            element.append(dom.Text(node[2]))
            parent.append(element)
            return
        element = dom.el(node[1])
        for child in node[2]:
            walk(child, element)
        parent.append(element)
        seen.append(" ")

    root = dom.el("#root")
    for block in blocks:
        walk(block, root)
    out.append(dom.serialize(root))
    return "".join(out), seen


class TokensTest(unittest.TestCase):

    @given(TEXT)
    def test_a_token_is_a_run_of_lowercase_letters_and_digits(self, text):
        for token in search.tokens(text):
            self.assertRegex(token, r"\A[a-z0-9]+\Z")

    @given(TEXT, TEXT)
    def test_a_space_splits_and_nothing_else_joins(self, a, b):
        self.assertEqual(search.tokens(a + " " + b), search.tokens(a) + search.tokens(b))

    @given(st.text(alphabet=st.characters(max_codepoint=127), max_size=40))
    def test_in_ascii_case_does_not_matter(self, text):
        self.assertEqual(search.tokens(text), search.tokens(text.upper()))
        self.assertEqual(search.tokens(text), re.findall(r"[a-z0-9]+", text.lower()))


class VisibleTextTest(unittest.TestCase):

    @given(PAGE)
    def test_what_a_reader_sees_and_nothing_else(self, blocks):
        markup, seen = page_markup(blocks)
        self.assertEqual(search.visible_text(markup), collapse("".join(seen)))


class BuildTest(unittest.TestCase):

    @given(st.lists(st.tuples(TEXT, TEXT, st.lists(TEXT, max_size=3), PAGE), max_size=4))
    def test_every_word_of_a_page_is_in_the_index_under_it(self, pages):
        made = [SimpleNamespace(title=title, url=f"p{i}.html", section="s", description=description,
                                toc=[(2, f"h{j}", h) for j, h in enumerate(headings)],
                                body=page_markup(blocks)[0])
                for i, (title, description, headings, blocks) in enumerate(pages)]
        data = json.loads(search.build(made, {"rmp::x": "reference/x.html#x"}, {"rmp::x": ("function", "Does.")}))
        self.assertEqual(len(data["docs"]), len(made))
        self.assertEqual(data["symbols"], [{"n": "rmp::x", "u": "reference/x.html#x", "k": "function", "d": "Does."}])
        hits = {(w, d): v for w, entries in data["index"].items() for d, v in entries}
        for i, page in enumerate(made):
            words = {w: 10 for w in search.tokens(page.title)}
            for h in [t for _l, _i, t in page.toc]:
                words.update({w: max(words.get(w, 0), 4) for w in search.tokens(h)})
            words.update({w: max(words.get(w, 0), 2) for w in search.tokens(page.description)})
            words.update({w: max(words.get(w, 0), 1) for w in search.tokens(search.visible_text(page.body))
                          if w not in search.STOP and len(w) > 1})
            for w, least in words.items():
                self.assertGreaterEqual(hits.get((w, i), 0), min(least, 99), (w, i))
        for entries in data["index"].values():
            weights = [v for _d, v in entries]
            self.assertEqual(weights, sorted(weights, reverse=True))
            self.assertTrue(all(1 <= v <= 99 for v in weights))


if __name__ == "__main__":
    unittest.main()
