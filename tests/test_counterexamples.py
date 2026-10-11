"""What the property tests found, each a named case: checked on every run
and on every machine -- Hypothesis or not -- and not only when the search
happens to find it again.

Every case here failed before the fix it is named after (the commit that
added it says which), and each class names the property that found it, in
tests/test_<module>_property.py.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from under_test import DOCS, load  # noqa: E402

cxx = load("cxx")
dom = load("dom")


class MaskCounterexamples(unittest.TestCase):
    """test_cxx_property.MaskTest"""

    def test_a_raw_string_never_closed_keeps_its_last_newline(self):
        # Was 'R" "': the last character of the text became the closing quote.
        self.assertEqual(cxx.mask('R"(\n'), 'R" \n')

    def test_a_raw_string_never_closed_runs_to_the_end(self):
        self.assertEqual(cxx.mask('R"x(a;\n}'), 'R"    \n ')

    def test_a_line_splice_in_a_string_keeps_its_newline(self):
        # Was '"    "': the newline after the backslash became a space, and
        # every line below it was read one line up.
        self.assertEqual(cxx.mask('"a\\\nb";'), '" \\\n ";')
        self.assertEqual(cxx.mask("'\\\n'"), "'\\\n'")

    def test_masking_a_splice_twice_reads_the_same_literal(self):
        once = cxx.mask('"a\\\nb" + x; "c"')
        self.assertEqual(cxx.mask(once), once)
        self.assertIn("+ x;", once)


class ReadHeaderCounterexamples(unittest.TestCase):
    """test_cxx_property.ReadHeaderTest: a header it cannot read is a
    ParseError naming the line, never another exception."""

    def refused(self, text: str, line: int, says: str):
        with self.assertRaises(cxx.ParseError) as caught:
            cxx.read_header("include/rmp/x.h", text)
        self.assertEqual((caught.exception.header, caught.exception.line), ("include/rmp/x.h", line))
        self.assertIn(says, caught.exception.message)

    def test_a_define_with_no_name(self):
        # Was AttributeError: 'NoneType' object has no attribute 'group'.
        self.refused("#define ", 1, "a #define with no name")
        self.refused("namespace rmp {\n#define (x) x\n}", 2, "a #define with no name")

    def test_a_template_whose_default_holds_a_greater_than(self):
        # Was AttributeError: the template was cut at the `>` of `(1>2)`,
        # and what was left was no scope's head.
        root = cxx.read_header("include/rmp/x.h", "namespace rmp {\ntemplate <int N = (1>2)> struct T {\n};\n}")
        t = next(e for e in root.walk() if e.qualname == "rmp::T")
        self.assertEqual((t.kind, t.template, t.line), ("struct", "template <int N = (1>2)>", 2))

    def test_a_scope_whose_head_is_no_scope_s(self):
        """What statement_end() took for a scope and declaration() cannot read
        as one -- the two disagreed on the template before (1>2) -- is a
        ParseError, whatever they disagree on next."""
        reader = cxx.HeaderReader("include/rmp/x.h", "x")
        with self.assertRaises(cxx.ParseError) as caught:
            reader.declaration("int f() {}", 3, reader.root, "public", "", (0, 0), "file")
        self.assertIn("cannot read the head of this scope", caught.exception.message)
        self.assertEqual(caught.exception.line, 3)

    def test_a_value_with_a_shift_keeps_its_spaces(self):
        # Was '(1 <<2)': collapse() took the second < for a template's.
        root = cxx.read_header("include/rmp/x.h", "namespace rmp {\ninline constexpr int K = (1 << 2);\n"
                                                  "using M = std::map<\n    int, float>;\n}")
        values = {e.name: (e.value, e.signature) for e in root.walk()}
        self.assertEqual(values["K"], ("(1 << 2)", "inline constexpr int K"))
        self.assertEqual(values["M"][1], "using M = std::map<int, float>")

    def test_a_banner_inside_a_class_opens_no_group_after_it(self):
        # Was 'Also inside': rmp::RayQuery and rmp::RayHit stood under "Identity
        # and life", a banner inside class Object, on the reference page of
        # the rmp namespace -- and rmp::save under Value's "Structure".
        root = cxx.read_header("include/rmp/x.h", "\n".join([
            "namespace rmp {", "// ----------", "// Outside.", "// ----------", "int a;", "",
            "// A class.", "class C {", "public:", "    // ----------", "    // Inside.", "    // ----------",
            "    int b;", "    // --- also inside ---", "    int c;", "};", "", "// After.", "int d;", "}"]))
        groups = {e.name: e.group for e in root.walk()}
        self.assertEqual([groups[n] for n in "abcd"], ["Outside", "Inside", "Also inside", "Outside"])

    def test_scopes_nested_past_the_limit(self):
        # Was RecursionError, a thousand frames down.
        deep = "namespace a {\n" * 2000 + "int x;\n" + "}\n" * 2000
        self.refused(deep, cxx.MAX_NESTING + 1, f"scopes nested deeper than {cxx.MAX_NESTING}")

    def test_scopes_nested_to_the_limit_are_read(self):
        text = "namespace a {\n" * cxx.MAX_NESTING + "int x;\n" + "}\n" * cxx.MAX_NESTING
        root = cxx.read_header("include/rmp/x.h", text)
        x = next(e for e in root.walk() if e.name == "x")
        self.assertEqual(x.qualname, "::".join(["a"] * cxx.MAX_NESTING + ["x"]))


class SerializeCounterexamples(unittest.TestCase):
    """test_dom_property.SerializeTest: what serialize() writes reads back
    as the tree, or it refuses."""

    def refused(self, node, says: str):
        root = dom.el("#root", None, node) if not isinstance(node, dom.Comment) else dom.el("#root")
        if isinstance(node, dom.Comment):
            root.append(node)
        with self.assertRaisesRegex(dom.HtmlError, says):
            dom.serialize(root)

    def test_a_comment_a_browser_would_end_early(self):
        # Was '<!-->-->': a browser reads an empty comment, and "-->" on the page.
        for data in (">", "->", "a-->b", "a--!>b", "x<!-"):
            with self.subTest(data=data):
                self.refused(dom.Comment(data), "cannot be written as a comment")

    def test_a_comment_a_browser_reads_as_written(self):
        for data in (" ok ", "a - b", "<!-- nested", "a->b", "-x-"):
            with self.subTest(data=data):
                root = dom.el("#root")
                root.append(dom.Comment(data))
                again, errors = dom.parse(dom.serialize(root))
                self.assertEqual((errors, again.children[0].data), ([], data))

    def test_a_script_that_says_its_own_end_tag(self):
        # Was '<script></SCRIPT></script>': the page's script ended early.
        self.refused(dom.el("div", None, dom.el("script", None, "x = '</SCRIPT>';")), "cannot say </script>")
        self.refused(dom.el("style", None, "a{} </style >"), "cannot say </style>")

    def test_a_text_only_element_holding_markup(self):
        # Was '<textarea><!----></textarea>': read back as text.
        area = dom.el("textarea")
        area.append(dom.Comment(""))
        self.refused(area, "<textarea> holds text and nothing else")
        self.refused(dom.el("title", None, dom.el("b", None, "x")), "<title> holds text and nothing else")
        self.refused(dom.el("script", None, dom.el("b")), "<script> holds text and nothing else")

    def test_children_where_nothing_can_be_held(self):
        self.refused(dom.el("br", None, "x"), "void element")
        self.refused(dom.el("path", {"/": ""}, "x"), "written self-closed")

    def test_self_closed_only_inside_an_svg(self):
        self.refused(dom.el("p", {"/": ""}), "not a void element")
        self.assertEqual(dom.serialize(dom.el("svg", None, dom.el("path", {"/": ""}))), "<svg><path/></svg>")

    def test_a_name_that_cannot_be_written(self):
        # Was '</><//>', and '<_></_>': a tag starts with a letter.
        self.refused(dom.el("/"), "cannot be written as the name")
        self.refused(dom.el("_"), "cannot be written as the name")
        self.refused(dom.el("p", {"a b": "c"}), "cannot be written as the name")


class ParseCounterexamples(unittest.TestCase):
    """test_dom_property.ParseTest: markup a browser repairs in silence is an
    error, not a guess the page ships."""

    def says(self, markup: str, *expected: str):
        _root, errors = dom.parse(markup)
        for text in expected:
            self.assertTrue(any(text in str(e) for e in errors), (markup, [str(e) for e in errors]))

    def test_markup_that_never_ends(self):
        # Each swallowed `<p id="end">end</p>` after it without a word.
        end = '<p id="end">end</p>'
        self.says("<!--" + end, "never ends")
        self.says("<a href='x" + end, "never ends")
        self.says("x <", "never ends")

    def test_what_the_parser_drops_or_turns_into_a_comment(self):
        self.says("<?x?>", "processing instruction")
        self.says("<p></<p id=\"end\">end</p>", "is not a tag")
        self.says("</ p>", "is not a tag")
        self.says("<!-<!-->", "is not a tag")
        self.says("</>", "closes nothing")

    def test_a_doctype_anywhere_but_first(self):
        self.says("<p><!DOCTYPE<p id=\"end\">end</p>", "is not <!doctype html> at the start")
        self.says("<p>x</p><!doctype html>", "is not <!doctype html> at the start")
        self.assertEqual(dom.parse("<!doctype html>\n<p>x</p>")[1], [])

    def test_a_tag_that_lost_its_quote_or_its_end(self):
        self.says('<p/<p id="end">end</p>', "an attribute called '<p'")
        self.says('<p><img src=x<p id="end">end</p>', "a < inside a tag")
        self.assertEqual(dom.parse('<a title="a<b" href=x>y</a>')[1], [])


class TransformCounterexamples(unittest.TestCase):
    """What serialize() refuses, in a page the build writes: a problem of
    the html gate, with the page and the line -- not a traceback, and not
    the markup a browser would read as something else."""

    def test_a_page_whose_comment_a_browser_would_end_early(self):
        framework = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))
        if not (framework / "include" / "rmp").is_dir():
            self.skipTest("no framework checkout: set RMP_FRAMEWORK")
        site = load("site")
        built = site.Site(framework=framework)
        root = dom.el("#root", None, dom.el("p", None, "x"))
        root.append(dom.Comment("a-->b", 7))
        page = site.Page(url="x.html", title="X", description="", section="", source="content/x.html", root=root)
        built.transform(page)
        self.assertEqual([(p.gate, p.where, p.line) for p in built.problems], [("html", "content/x.html", 7)])
        self.assertIn("cannot be written as a comment", built.problems[0].message)
        self.assertEqual(page.body, "")


if __name__ == "__main__":
    unittest.main()
