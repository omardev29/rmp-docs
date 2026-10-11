"""tools/rmpdocs/cxx.py held to its promises for ANY text.

  mask()         same length, every newline where it was, only comments and
                 the insides of literals turned into spaces -- the braces,
                 parentheses and semicolons left are only ever code.
  split_comment  the code of a line and its trailing comment, never a // in
                 a string.
  read_header    a header it cannot read is a ParseError naming the header
                 and the line, never another exception: the build reports a
                 ParseError as a problem, and anything else is a traceback.
                 And a header written in the grammar reads back as what was
                 written: every declaration, its kind, its qualified name,
                 its line and its doc.

Every property here was seen red: the commit that added this file says how.
A counterexample becomes a named case in tests/test_counterexamples.py.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hypothesis_profiles  # noqa: E402,F401  (first: the profile, or the skip)
from hypothesis import given, strategies as st  # noqa: E402
from under_test import load  # noqa: E402

cxx = load("cxx")
ParseError = cxx.ParseError

# What mask() and the reader turn on, mixed with anything at all.
WORDS = (
    list('/*"\'R(\\)\n{}[];:<>=,#&~ u8L1x_') + [
        "//", "/*", "*/", 'R"', 'R"(', ')"', 'R"x(', ')x"', 'u8"', "\\\n", "1'000",
        "namespace ", "class ", "struct ", "enum ", "enum class ", "union ", "template <",
        "typename T", "requires ", "friend ", "operator", "public:", "private:", "using ",
        "#define ", "#define\n", "#if X\n", "#endif\n", "\n#", "static ", "constexpr ",
        "const ", "virtual ", "= 0", "= delete", "= default", "[[nodiscard]] ", "->", "::",
        "detail", "~", "\n// ----------\n", "// a doc\n", "\n\n"])
DECISIVE = st.sampled_from(WORDS)
SOURCE = st.lists(st.one_of(DECISIVE, st.characters()), max_size=120).map("".join)
# The same, a line at a time: the reader reads a `#` or a banner only where a
# line starts.
LINES = st.lists(st.lists(st.one_of(DECISIVE, DECISIVE, st.characters()), max_size=8).map("".join),
                 max_size=16).map("\n".join)


def newlines(text: str) -> list[int]:
    return [i for i, c in enumerate(text) if c == "\n"]


def blanked(text: str) -> str:
    return "".join(c if c == "\n" else " " for c in text)


def literal_blanked(inside: str) -> str:
    """The inside of a quoted literal as mask() leaves it: spaces, and a line
    splice -- a backslash and the newline after it -- kept whole."""
    return "".join(part if part == "\\\n" else blanked(part) for part in re.split(r"(\\\n)", inside))


# One piece of C++, as written and as mask() must leave it: code kept, a
# comment all spaces, a literal's quotes kept and its inside spaces.
_PLAIN = st.characters(exclude_characters='\n"\'\\', exclude_categories=("Cs",))
# Escapes, a line splice, and what would be a comment outside the quotes.
_TRICKY = st.sampled_from(['\\"', "\\'", "\\\\", "\\n", "\\\n", "//", "/*"])
# Code: a `/` alone is division, never the start of a comment.
CODE = st.text(alphabet=st.sampled_from("abcxyz019_ ;(){}=+-<>:,/\n"), max_size=12).filter(
    lambda c: "//" not in c and not c.endswith("/"))
LINE_COMMENT = st.text(alphabet=st.characters(exclude_characters="\n"), max_size=20).map(
    lambda said: "//" + said)
BLOCK_COMMENT = st.text(alphabet=st.characters(exclude_characters="*"), max_size=20).map(
    lambda said: "/*" + said + "*/")
STRING = st.lists(st.one_of(_PLAIN, _TRICKY), max_size=12).map("".join).map(lambda s: f'"{s}"')
CHARACTER = st.one_of(_PLAIN, _TRICKY).map(lambda c: f"'{c}'")
RAW = st.text(alphabet=st.characters(exclude_characters=")"), max_size=20).map(lambda s: f'R"x({s})x"')
PIECE = st.one_of(
    CODE.map(lambda c: (c, c)),
    st.one_of(LINE_COMMENT.map(lambda w: w + "\n"), BLOCK_COMMENT).map(lambda w: (w, blanked(w))),
    st.one_of(STRING, CHARACTER).map(lambda w: (w, w[0] + literal_blanked(w[1:-1]) + w[-1])),
    RAW.map(lambda w: (w, 'R"' + blanked(w[2:-1]) + '"')),
)


class MaskTest(unittest.TestCase):

    @given(SOURCE)
    def test_every_offset_and_every_newline_still_holds(self, text):
        out = cxx.mask(text)
        self.assertEqual(len(out), len(text))
        self.assertEqual(newlines(out), newlines(text))
        changed = [i for i in range(len(text)) if out[i] != text[i]]
        self.assertTrue(all(out[i] == " " for i in changed), [(text[i], out[i]) for i in changed])

    @given(st.one_of(SOURCE, st.lists(PIECE, max_size=12).map(lambda ps: ",".join(w for w, _m in ps))))
    def test_masking_twice_is_masking_once(self, text):
        once = cxx.mask(text)
        self.assertEqual(cxx.mask(once), once)

    @given(st.lists(st.one_of(st.sampled_from("/*{};"), st.characters(exclude_characters='"\'')),
                    max_size=120).map("".join).filter(lambda c: "//" not in c and "/*" not in c))
    def test_code_with_no_comment_and_no_literal_is_left_alone(self, code):
        self.assertEqual(cxx.mask(code), code)

    @given(st.lists(PIECE, max_size=12))
    def test_exactly_the_comments_and_the_insides_of_literals_go(self, pieces):
        """A text built of known pieces, each followed by a `,`: what mask()
        gives is known before it runs."""
        text = "".join(f"{written}," for written, _ in pieces)
        expected = "".join(f"{masked}," for _, masked in pieces)
        self.assertEqual(cxx.mask(text), expected)


class SplitCommentTest(unittest.TestCase):

    @given(st.lists(st.one_of(CODE.filter(lambda c: "\n" not in c), STRING, CHARACTER), max_size=6),
           st.one_of(st.none(), st.text(alphabet=st.characters(exclude_characters="\n"), max_size=20)))
    def test_the_comment_is_what_follows_the_first_slashes_outside_a_literal(self, parts, comment):
        code = ",".join(parts).replace("\\\n", "\\n")
        line = code if comment is None else f"{code}//{comment}"
        self.assertEqual(cxx.split_comment(line), (code, "" if comment is None else comment.strip()))


# Whole lines of a header, any of which can follow any other.
GRAMMAR_LINE = st.sampled_from([
    "#pragma once", "#define", "#define X", "#define X 1", "#define F(a, b) ((a) + (b))", "#define G \\",
    "#if RMP_X", "#ifdef X", "#else", "#elif Y", "#endif", "# define Y", "#include <x.h>",
    "namespace rmp {", "namespace detail {", "namespace {", "}", "};", "} // namespace rmp",
    "class Widget {", "class Widget : public Base {", "struct S {", "struct Value::Ref {", "union U {",
    "enum class E {", "enum E : int {", "A,", "B = 2,", "C = (1 << 3), // trailing", "{", ")", "(", ";",
    "public:", "private:", "protected:", "template <class T>", "template <int N = (1>2)>",
    "template <class T> requires std::is_same_v<T, int>", "requires (sizeof(T) > 1)",
    "int x;", "int x = 1;", "static constexpr int MAX = 3;", "float f(int a, float b = 1.0f);",
    "void g() const;", "virtual void h() = 0;", "Widget(const Widget &) = delete;", "~Widget();",
    "Widget &operator=(Widget &&other) noexcept;", "bool operator==(const Widget &) const = default;",
    "explicit operator bool() const;", "using Fn = void (*)(int);", "using namespace std;",
    "friend class Other;", "friend bool operator<(A, B);", "struct { int a; } ours;",
    "struct { int a; };", "auto f() -> int;", "[[nodiscard]] int n() const;", "inline int k() { return 1; }",
    "int arr[3] = {1, 2, 3};", "static_assert(true);", "class Fwd;", "Widget() : a(1) {}",
    "// a doc", "/// three slashes", "// NOLINT", "// ---------- a banner ----------",
    "// ----------", "// --- marker ---", "/* a block", "comment */", "R\"x(raw", ")x\"", "\"str",
    "'c'", "1'000", "", "   ", "\t#define T", "x \\",
])

# Balanced pieces: a scope's head, `{`, what is inside, `};` -- most of what
# this writes gets past the braces, to where the declarations are read.
HEAD = st.sampled_from([
    "namespace a", "namespace detail", "namespace", "namespace a::b", "struct S", "class C",
    "class C : public B", "class C final", "union U", "struct", "enum class E", "enum E : int",
    "template <class T> struct T", "template <int N = (1>2)> struct T",
    "template <class T = std::less<>> class C", "template <class T> requires X struct R",
    "struct Value::Ref", "struct S::Inner", "inline int f()", "Widget() : a(1)", "int arr[2] =",
    "auto g() -> int", "void h() const", "[[nodiscard]] struct N", "friend struct F",
])
BLOCK = st.recursive(
    GRAMMAR_LINE,
    lambda inner: st.tuples(st.lists(st.sampled_from(["// a doc", "// ----------", ""]), max_size=2),
                            HEAD, st.lists(inner, max_size=4)).map(
        lambda t: "\n".join(t[0] + [t[1] + " {"] + t[2] + ["};"])),
    max_leaves=12)

# A header in the grammar, from a model: what read_header must find in it.
NAME = st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True).filter(
    lambda n: n not in KEYWORDS and not n.startswith("detail"))
KEYWORDS = {"class", "struct", "enum", "union", "namespace", "using", "template", "typename",
            "requires", "friend", "operator", "public", "private", "protected", "static",
            "constexpr", "const", "virtual", "inline", "return", "int", "float", "void",
            "bool", "auto", "delete", "default", "final", "override", "noexcept", "explicit"}
DOC = st.lists(st.text(alphabet=st.sampled_from("abc xyz,.;:()"), min_size=1, max_size=20).map(
    str.strip).filter(bool), max_size=2)


@st.composite
def declarations(draw, depth=0, in_struct=False):
    """[(kind, name, doc, lines, children)]: a scope's declarations, each
    separated by a blank line, so none is a run of the one above."""
    out = []
    names = set()
    for _ in range(draw(st.integers(0, 4))):
        name = draw(NAME)
        if name in names:
            continue
        names.add(name)
        doc = draw(DOC)
        kind = draw(st.sampled_from(["function", "field", "constant", "enum", "alias"]
                                    + (["struct"] if depth < 2 else [])
                                    + (["namespace"] if depth < 2 and not in_struct else [])))
        children = []
        if kind == "function":
            lines = [f"float {name}(int x, const char *y = \"a;b{{\");"]
        elif kind == "field":
            lines = [f"int {name} = 3;"]
        elif kind == "constant":
            lines = [f"{'static' if in_struct else 'inline'} constexpr int {name.upper()}_K = (1 << 2);"]
            name = f"{name.upper()}_K"
        elif kind == "alias":
            lines = [f"using {name} = int;"]
        elif kind == "enum":
            members = draw(st.lists(NAME.map(str.upper), min_size=1, max_size=3, unique=True))
            lines = [f"enum class {name} {{"] + [f"    {m}," for m in members] + ["};"]
            children = [("member", m, [], [], []) for m in members]
        else:
            children = draw(declarations(depth + 1, in_struct or kind == "struct"))
            body = [line for child in children for line in child_lines(child)]
            opener = f"struct {name} {{" if kind == "struct" else f"namespace {name} {{"
            lines = [opener] + ["    " + line if line else "" for line in body] + \
                    (["};"] if kind == "struct" else ["}"])
        out.append((kind, name, doc, lines, children))
    return out


def child_lines(declaration) -> list[str]:
    _kind, _name, doc, lines, _children = declaration
    return [""] + [f"// {d}" for d in doc] + lines


def header_of(model) -> str:
    body = [line for d in model for line in child_lines(d)]
    return "\n".join(["#pragma once", "", "namespace rmp {"] + body + ["}", ""])


def expected(model, prefix="rmp", first=4):
    """[(kind, qualname, line, doc)] in the order read_header meets them."""
    out = []
    line = first
    for kind, name, doc, lines, children in model:
        line += 1 + len(doc)
        q = f"{prefix}::{name}"
        out.append((kind, q, line, "\n".join(doc)))
        if kind in ("struct", "namespace"):
            out += expected(children, q, line + 1)
        elif kind == "enum":
            out += [("member", f"{q}::{m}", line + 1 + i, "") for i, (_k, m, *_r) in enumerate(children)]
        line += len(lines)
    return out


class ReadHeaderTest(unittest.TestCase):

    @given(st.one_of(SOURCE, LINES))
    def test_anything_it_cannot_read_is_a_parse_error(self, text):
        try:
            cxx.read_header("include/rmp/x.h", text)
        except ParseError as e:
            self.assertEqual(e.header, "include/rmp/x.h")
            self.assertIsInstance(e.line, int)

    @given(st.lists(st.one_of(GRAMMAR_LINE, BLOCK, BLOCK, LINES), max_size=12).map("\n".join))
    def test_the_grammar_s_own_lines_in_any_order_are_read_or_refused(self, text):
        try:
            cxx.read_header("include/rmp/x.h", text)
        except ParseError:
            pass

    @given(declarations())
    def test_a_header_in_the_grammar_reads_back_as_written(self, model):
        root = cxx.read_header("include/rmp/x.h", header_of(model))
        got = [(e.kind, e.qualname, e.line, e.doc) for e in root.walk()
               if e.kind not in ("file",) and e.qualname != "rmp"]
        self.assertEqual(got, expected(model))


if __name__ == "__main__":
    unittest.main()
