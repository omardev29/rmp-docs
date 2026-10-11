"""What the property tests found, each a named case: checked on every run
and on every machine -- Hypothesis or not -- and not only when the search
happens to find it again.

Every case here failed before the fix it is named after (the commit that
added it says which), and each class names the property that found it, in
tests/test_<module>_property.py.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from under_test import load  # noqa: E402

cxx = load("cxx")


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

    def test_scopes_nested_past_the_limit(self):
        # Was RecursionError, a thousand frames down.
        deep = "namespace a {\n" * 2000 + "int x;\n" + "}\n" * 2000
        self.refused(deep, cxx.MAX_NESTING + 1, f"scopes nested deeper than {cxx.MAX_NESTING}")

    def test_scopes_nested_to_the_limit_are_read(self):
        text = "namespace a {\n" * cxx.MAX_NESTING + "int x;\n" + "}\n" * cxx.MAX_NESTING
        root = cxx.read_header("include/rmp/x.h", text)
        x = next(e for e in root.walk() if e.name == "x")
        self.assertEqual(x.qualname, "::".join(["a"] * cxx.MAX_NESTING + ["x"]))


if __name__ == "__main__":
    unittest.main()
