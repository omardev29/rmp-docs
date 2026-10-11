"""tools/rmpdocs/highlight.py held to its promise for ANY text, in every
language: it changes colours, never text -- what comes out is the source,
escaped, with a <span class> around some tokens and nothing else.

tests/test_highlight.py shows the promise on a sample per language; this is
the same promise over everything Hypothesis can write, leaning on the
characters each scanner decides on -- st.text() alone almost never writes
`R"x(`, `${`, `[[` or a `#` at the start of a line.

Every property here was seen red: the commit that added this file says how.
A counterexample becomes a named case in tests/test_counterexamples.py.
"""

from __future__ import annotations

import html
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hypothesis_profiles  # noqa: E402,F401  (first: the profile, or the skip)
from hypothesis import given, strategies as st  # noqa: E402
from under_test import load  # noqa: E402

highlight = load("highlight")
LANGS = frozenset(highlight.LANGS)

# What any of the scanners turns on, mixed with anything at all.
DECISIVE = st.sampled_from(
    list("\"'`\\/*#$@{}()[]<>&;|=:-_.~+\n\t rRuUL0189xXeEfF") + [
        "//", "/*", "*/", 'R"', 'R"(', ')"', 'R"x(', ')x"', 'u8"', "u8'", "L'", "[[", "]]",
        "#include ", "#define ", "#if ", "\n#", "\n  #", "${", "${{", "}}", "$(", "--", "-x",
        "0x1F", "1'000", "1e-3f", ".5", '"""', "true", "false", "null", "nan", "inf",
        "class ", "return", "if", "then", "fi", "Set-Item", "&amp;", "&lt;", "<b>", "</span>",
        "MAX_X", "PascalCase", "f(", " # ", "a: ", "- b: ", "[x]", "[[a.b]]", "k = 1"])
# What opens a span in one language or another, and something hostile inside
# it: a span's text has to come out escaped like any other.
OPENS = st.sampled_from(["//", "/*", "#", "\n#define X ", "\n#include ", '"', "'", "`", 'R"(', "${",
                         "[[", "- ", "\nkey = \"", "-x=", "$", "0x", "1e"])
INSIDE = st.text(alphabet=st.sampled_from("<>&\"' ab/*#;\n"), max_size=8)
SPAN = st.tuples(OPENS, INSIDE).map("".join)
SOURCE = st.lists(st.one_of(DECISIVE, SPAN, st.characters()), max_size=80).map("".join)
LANG = st.sampled_from(highlight.LANGS)
UNKNOWN = st.text(max_size=8).filter(lambda lang: lang not in LANGS)

# One line of C++ and the class it must come out as, whole: a literal or a
# comment is one span, and plain code is none of either.
_INSIDE = st.characters(exclude_characters='\n"\'\\', exclude_categories=("Cs",))
_ESCAPE = st.sampled_from(['\\"', "\\'", "\\\\", "\\n", "\\0", "\\x41"])
_BODY = st.lists(st.one_of(_INSIDE, _ESCAPE), max_size=12).map("".join)
PIECE = st.one_of(
    st.tuples(st.sampled_from(["", "u8", "u", "U", "L"]), _BODY).map(lambda p: (f'{p[0]}"{p[1]}"', "s")),
    st.tuples(st.sampled_from(["", "u8", "u", "U", "L"]), st.one_of(_INSIDE, _ESCAPE)).map(
        lambda p: (f"{p[0]}'{p[1]}'", "s")),
    st.tuples(st.sampled_from(["", "x", "end", "a b"]),
              st.text(alphabet=st.characters(exclude_characters="\n", exclude_categories=("Cs",)),
                      max_size=12)).map(lambda p: (f'R"{p[0]}({p[1]}){p[0]}"', "s")
                                        if f"){p[0]}\"" not in p[1] and " " not in p[0]
                                        else ('"plain"', "s")),
    st.text(alphabet=st.characters(exclude_characters="\n", exclude_categories=("Cs",)),
            max_size=16).map(lambda said: ("//" + said, "c")),
    st.text(alphabet=st.characters(exclude_characters="*\n", exclude_categories=("Cs",)),
            max_size=16).map(lambda said: ("/*" + said + "*/", "c")),
    st.text(alphabet=st.sampled_from("abcxyzAZ019_ ;(){}=+-<>,.&|!~^%?:"), max_size=16).filter(
        lambda code: not code.lstrip().startswith("#")).map(lambda code: (code, "")),
)

CLASSES = "ktfsncpmav"
# The whole of what highlight() may write: escaped text, and spans of one
# known class around escaped text -- never a span inside a span.
TEXT = r"(?:[^<>&]|&(?:amp|lt|gt);)"
SHAPE = re.compile(rf"(?:{TEXT}|<span class=\"[{CLASSES}]\">{TEXT}+</span>)*")


class HighlightTest(unittest.TestCase):

    @given(SOURCE, LANG)
    def test_the_text_survives_exactly(self, src, lang):
        self.assertEqual(highlight.plain(highlight.highlight(src, lang)), src)

    @given(SOURCE, LANG)
    def test_only_escaped_text_and_known_spans_come_out(self, src, lang):
        out = highlight.highlight(src, lang)
        self.assertRegex(out, rf"\A{SHAPE.pattern}\Z")

    @given(SOURCE, LANG)
    def test_the_spans_add_nothing_but_colour(self, src, lang):
        """Without its tags the output is the source escaped, character for
        character: a span never swallows, doubles or reorders text."""
        out = highlight.highlight(src, lang)
        self.assertEqual(re.sub(r"</?span[^>]*>", "", out), html.escape(src, quote=False))

    @given(SOURCE)
    def test_text_is_escaped_and_nothing_else(self, src):
        self.assertEqual(highlight.highlight(src, "text"), html.escape(src, quote=False))

    @given(SOURCE, UNKNOWN)
    def test_a_language_it_does_not_know_is_an_error(self, src, lang):
        with self.assertRaisesRegex(ValueError, "no highlighter for"):
            highlight.highlight(src, lang)

    @given(st.lists(PIECE, min_size=1, max_size=10), st.sampled_from(["cpp", "c"]))
    def test_a_literal_or_a_comment_is_one_span_in_cpp(self, pieces, lang):
        """C++ built of known pieces, one to a line: every string, character
        literal and comment comes out as exactly one span of its class, whole,
        whatever is inside it."""
        out = highlight.highlight("\n".join(written for written, _cls in pieces), lang).split("\n")
        self.assertEqual(len(out), len(pieces))
        for (written, cls), line in zip(pieces, out):
            if cls:
                self.assertEqual(line, f'<span class="{cls}">{html.escape(written, quote=False)}</span>')
            else:
                self.assertNotIn('class="s"', line)
                self.assertNotIn('class="c"', line)


if __name__ == "__main__":
    unittest.main()
