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


NAME = st.from_regex(r"rmp::[a-z]{1,4}(::[a-z_]{1,6})?", fullmatch=True)
SUMMARY = st.tuples(st.sampled_from(["function", "class", "field", ""]),
                    st.text(alphabet=st.characters(exclude_categories=("Cs",)), max_size=200))


def expected_index(made) -> dict:
    """The inverted index build() promises, worked out on its own: per word,
    [page, weight] -- a title's word 10, a heading's 4, the description's 2,
    the text's 1 (not a stop word, not one letter), added up and capped at 99
    -- heaviest first, then in page order."""
    weights: dict[str, dict[int, int]] = {}
    for i, page in enumerate(made):
        said = ([(w, 10) for w in search.tokens(page.title)]
                + [(w, 4) for _l, _i, h in page.toc for w in search.tokens(h)]
                + [(w, 2) for w in search.tokens(page.description)]
                + [(w, 1) for w in search.tokens(search.visible_text(page.body))
                   if w not in search.STOP and len(w) > 1])
        for w, weight in said:
            weights.setdefault(w, {})
            weights[w][i] = weights[w].get(i, 0) + weight
    return {w: sorted(([d, min(v, 99)] for d, v in weights[w].items()), key=lambda e: (-e[1], e[0]))
            for w in sorted(weights)}


class BuildTest(unittest.TestCase):

    @given(st.lists(st.tuples(TEXT, TEXT, st.lists(TEXT, max_size=24), PAGE), max_size=4),
           st.dictionaries(NAME, st.text(max_size=12), max_size=4),
           st.dictionaries(NAME, SUMMARY, max_size=4))
    def test_the_json_is_exactly_what_the_pages_say(self, pages, reference, summaries):
        made = [SimpleNamespace(title=title, url=f"p{i}.html", section=f"s{i % 2}", description=description,
                                toc=[(2, f"h{j}", h) for j, h in enumerate(headings)],
                                body=page_markup(blocks)[0])
                for i, (title, description, headings, blocks) in enumerate(pages)]
        data = json.loads(search.build(made, reference, summaries))
        self.assertEqual(sorted(data), ["docs", "index", "symbols"])
        self.assertEqual(data["docs"], [
            {"t": p.title, "u": p.url, "s": p.section, "h": [h for _l, _i, h in p.toc][:20],
             "x": p.description or search.visible_text(p.body)[:160]} for p in made])
        self.assertEqual(data["symbols"], [
            {"n": name, "u": url, "k": summaries.get(name, ("", ""))[0],
             "d": summaries.get(name, ("", ""))[1][:140]} for name, url in sorted(reference.items())])
        self.assertEqual(data["index"], expected_index(made))

    def test_one_page_by_hand(self):
        """The model above, checked against numbers worked out by hand."""
        page = SimpleNamespace(title="Button button", url="b.html", section="ui", description="A button.",
                               toc=[(2, "x", "Button")], body="<p>the button, and a b</p>")
        data = json.loads(search.build([page], {}, {}))
        self.assertEqual(data["index"]["button"], [[0, 10 + 10 + 4 + 2 + 1]])
        self.assertEqual(data["index"]["a"], [[0, 2]])      # the description's: no stop words there
        self.assertNotIn("and", data["index"])                # the text's: a stop word
        self.assertNotIn("b", data["index"])                  # the text's: one letter
        self.assertEqual(data["index"], expected_index([page]))


if __name__ == "__main__":
    unittest.main()
