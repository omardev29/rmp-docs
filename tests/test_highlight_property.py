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


# One line, the language it is in, and the HTML it must come out as: what
# each scanner tells apart, by class. Text inside a literal or a comment is
# anything, escaped.
def span(cls: str, text: str) -> str:
    return f'<span class="{cls}">{html.escape(text, quote=False)}</span>'


def esc(text: str) -> str:
    return html.escape(text, quote=False)


SAID = st.text(alphabet=st.characters(exclude_characters="\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029",
                                       exclude_categories=("Cs",)), max_size=12)
INSIDE_QUOTES = st.text(alphabet=st.sampled_from("ab <>&;=#$/*-"), max_size=10)
WORD = st.from_regex(r"[a-z][a-z0-9_]{0,5}", fullmatch=True)
CAPS = st.from_regex(r"[A-Z][A-Z0-9_]{2,6}", fullmatch=True)
PASCAL = st.from_regex(r"[A-Z][a-z]{1,4}[A-Z][a-z]{1,4}", fullmatch=True)
NUMBER = st.sampled_from(["0", "42", "1.5", "1e3", "2.5e-3"])


def _not(words):
    return WORD.filter(lambda w: w not in words)


CPP_PLAIN = _not(highlight.CPP_KEYWORDS | highlight.C_EXTRA_KEYWORDS | highlight.CPP_TYPES)


def cases(langs, *leaves):
    """A strategy per leaf: (language, line, the HTML it must come out as)."""
    return [st.tuples(st.sampled_from(langs), leaf).map(lambda t: (t[0],) + t[1]) for leaf in leaves]


# Every case each scanner tells apart, drawn ALL of them in every example
# (test_each_scanner_tells_its_tokens_apart): one strategy choosing among
# fifty spent 200 examples so unevenly that a PowerShell keyword was never
# written, and mutmut's `w.upper() in PS_KEYWORDS` lived.
CASES = [
    # C and C++
    *cases(["cpp", "c"],
        SAID.map(lambda t: ("//" + t, span("c", "//" + t))),
        INSIDE_QUOTES.map(lambda t: (f'"{t}"', span("s", f'"{t}"'))),
        st.sampled_from(sorted(highlight.CPP_KEYWORDS)).map(lambda k: (k, span("k", k))),
        st.sampled_from(sorted(highlight.CPP_TYPES)).map(lambda t: (t + " x", span("t", t) + " x")),
        CPP_PLAIN.map(lambda w: (w + "(x)", span("f", w) + "(x)")),
        CAPS.map(lambda m: (m, span("m", m))),
        PASCAL.map(lambda t: (t, span("t", t))),
        st.sampled_from(["0", "42", "0x1F", "1.5f", "1'000", "2e-3", ".5"]).map(lambda n: (n, span("n", n))),
        WORD.map(lambda a: (f"[[{a}]]", span("a", f"[[{a}]]"))),
        WORD.map(lambda h: (f"#include <{h}.h>", span("p", "#include") + " " + span("s", f"<{h}.h>"))),
        CAPS.map(lambda m: (f"#define {m} 1", span("p", "#define") + " " + span("m", m) + " 1")),
        SAID.map(lambda t: (f"#if x //{t}", span("p", "#if") + " x " + span("c", "//" + t))),
    ),
    st.sampled_from(sorted(highlight.C_EXTRA_KEYWORDS)).map(lambda k: ("c", k, span("k", k))),
    # ...and C's own keywords are words in C++.
    st.sampled_from(["restrict x", "_Bool x"]).map(lambda w: ("cpp", w, w)),
    # TOML
    *cases(["toml"],
        SAID.map(lambda t: ("#" + t, span("c", "#" + t))),
        WORD.map(lambda w: (f"[{w}]", span("k", f"[{w}]"))),
        WORD.map(lambda w: (f"[[{w}.x]]", span("k", f"[[{w}.x]]"))),
        st.tuples(WORD, NUMBER).map(lambda t: (f"{t[0]} = {t[1]}", span("a", t[0]) + " = " + span("n", t[1]))),
        INSIDE_QUOTES.map(lambda t: (f'x = "{t}"', span("a", "x") + " = " + span("s", f'"{t}"'))),
        INSIDE_QUOTES.map(lambda t: (f"x = '{t}'", span("a", "x") + " = " + span("s", f"'{t}'"))),
        st.tuples(INSIDE_QUOTES, INSIDE_QUOTES).map(lambda t: (f'x = """{t[0]}\n{t[1]}"""', span("a", "x") + " = "
                                                              + span("s", f'"""{t[0]}\n{t[1]}"""'))),
        st.sampled_from(["true", "false"]).map(lambda b: (f"x = {b}", span("a", "x") + " = " + span("k", b))),
        st.sampled_from(["nan", "inf", "-inf", "+1_000"]).map(lambda n: (f"x = {n}", span("a", "x") + " = " + span("n", n))),
    ),
    # shell
    *cases(["shell"],
        SAID.map(lambda t: ("#" + t, span("c", "#" + t))),
        st.tuples(_not(highlight.SHELL_KEYWORDS), WORD).map(
            lambda t: (f"{t[0]} --{t[1]}", span("f", t[0]) + " " + span("a", f"--{t[1]}"))),
        _not(highlight.SHELL_KEYWORDS).map(lambda w: (f"echo ${w}", span("f", "echo") + " " + span("v", "$" + w))),
        WORD.map(lambda w: (f"echo ${{{w}}}", span("f", "echo") + " " + span("v", "${" + w + "}"))),
        INSIDE_QUOTES.filter(lambda t: "'" not in t).map(lambda t: (f"echo '{t}'", span("f", "echo") + " " + span("s", f"'{t}'"))),
        st.sampled_from(sorted(highlight.SHELL_KEYWORDS)).map(lambda k: (k, span("k", k))),
        _not(highlight.SHELL_KEYWORDS).map(lambda w: (f"a | {w}", span("f", "a") + " | " + span("f", w))),
    ),
    # PowerShell
    *cases(["powershell"],
        SAID.map(lambda t: ("#" + t, span("c", "#" + t))),
        WORD.map(lambda w: (f"${w}", span("v", "$" + w))),
        PASCAL.map(lambda t: (f"[{t}]", span("t", f"[{t}]"))),
        st.tuples(PASCAL, PASCAL).map(lambda t: (f"$x {t[0].title()}-{t[1]}",
                                                 span("v", "$x") + " " + span("f", f"{t[0].title()}-{t[1]}"))),
        st.tuples(_not(highlight.PS_KEYWORDS), WORD).map(
            lambda t: (f"{t[0]} -{t[1]}", span("f", t[0]) + " " + span("a", f"-{t[1]}"))),
        st.sampled_from(sorted(highlight.PS_KEYWORDS)).map(lambda k: (k.capitalize(), span("k", k.capitalize()))),
        INSIDE_QUOTES.filter(lambda t: "'" not in t).map(lambda t: (f"'{t}'", span("s", f"'{t}'"))),
    ),
    # CMake
    *cases(["cmake"],
        SAID.map(lambda t: ("#" + t, span("c", "#" + t))),
        WORD.map(lambda w: (f"{w}(x)", span("f", w) + "(x)")),
        CAPS.map(lambda m: (m, span("m", m))),
        WORD.map(lambda w: ("${" + w + "}", span("v", "${" + w + "}"))),
        INSIDE_QUOTES.map(lambda t: (f'"{t}"', span("s", f'"{t}"'))),
    ),
    # JSON
    *cases(["json"],
        st.tuples(WORD, NUMBER.filter(lambda n: "e" not in n)).map(
            lambda t: (f'"{t[0]}": -{t[1]}', span("a", f'"{t[0]}"') + ": " + span("n", f"-{t[1]}"))),
        INSIDE_QUOTES.filter(lambda t: '"' not in t).map(lambda t: (f'["{t}"]', "[" + span("s", f'"{t}"') + "]")),
        st.sampled_from(["true", "false", "null"]).map(lambda k: (f"[{k}]", "[" + span("k", k) + "]")),
    ),
    # YAML
    *cases(["yaml"],
        SAID.map(lambda t: ("#" + t, span("c", "#" + t))),
        WORD.map(lambda w: (f"{w}: x", span("a", w) + ": x")),
        WORD.map(lambda w: (f"- {w}: x", span("a", f"- {w}") + ": x")),
        WORD.map(lambda w: ("x: ${{ " + w + " }}", span("a", "x") + ": " + span("v", "${{ " + w + " }}"))),
        st.sampled_from(["true", "false", "null", "yes", "no"]).map(lambda k: (f"x: {k}", span("a", "x") + ": " + span("k", k))),
        INSIDE_QUOTES.filter(lambda t: "'" not in t).map(lambda t: (f"x: '{t}'", span("a", "x") + ": " + span("s", f"'{t}'"))),
    ),
]


class HighlightTest(unittest.TestCase):

    def setUp(self):
        # highlight() keeps a scanner a language once built: built in every
        # test, so that a test of one language is a test of its scanner.
        highlight._SCANNERS.clear()

    @given(st.data())
    def test_each_scanner_tells_its_tokens_apart(self, data):
        for case in CASES:
            lang, line, expected = data.draw(case)
            self.assertEqual(highlight.highlight(line, lang), expected, (lang, line))

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
