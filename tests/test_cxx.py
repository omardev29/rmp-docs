"""The header reader, on a fixture written to hold every shape of the
grammar in tools/rmpdocs/cxx.py -- and on the framework's real headers, which
must all read without an error."""

import os
import sys
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs.cxx import read_header  # noqa: E402

FIXTURE = DOCS / "tests" / "fixtures" / "headers" / "grammar.h"


class GrammarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = read_header("include/rmp/grammar.h", FIXTURE.read_text())
        cls.by = {}
        for e in cls.root.walk():
            cls.by.setdefault(e.qualname, []).append(e)

    def one(self, q):
        got = self.by.get(q, [])
        self.assertEqual(len(got), 1, f"{q}: {got}")
        return got[0]

    def test_the_file_block(self):
        self.assertTrue(self.root.doc.startswith("rmp/grammar.h -- every shape"))

    def test_a_banner_above_a_class_is_its_doc(self):
        self.assertIn("directly above a class", self.one("rmp::Widget").doc)

    def test_a_banner_inside_a_class_opens_a_group(self):
        draw = self.one("rmp::Widget::draw")
        self.assertEqual(draw.group, "Drawing. A banner inside a class opens a group")
        self.assertTrue(draw.covered)
        self.assertEqual(self.one("rmp::Widget::current").group, draw.group)

    def test_a_run_shares_one_doc(self):
        self.assertEqual(self.one("rmp::Widget::width").doc, "One doc for a run.")
        h = self.one("rmp::Widget::height")
        self.assertEqual((h.doc, h.run_doc, h.covered), ("", "One doc for a run.", True))

    def test_overloads(self):
        moves = self.by["rmp::Widget::move"]
        self.assertEqual([m.signature for m in moves], ["void move(float x, float y)", "void move(Vector2 to)"])

    def test_trailing_comments_and_initialisers(self):
        size = self.one("rmp::Widget::size")
        self.assertEqual((size.signature, size.value, size.trailing), ("float size", "1.0f", "in design units"))
        pos = self.one("rmp::Widget::position")
        self.assertEqual((pos.signature, pos.value, pos.covered), ("Vector2 position", "{ 10, 20 }", False))

    def test_special_members_are_hidden(self):
        hidden = {e.signature for e in self.root.walk() if e.deleted}
        for sig in ("Widget() = default", "~Widget()", "Widget(const Widget &) = delete",
                    "Widget &operator=(const Widget &) = delete", "Widget(Widget &&other) noexcept"):
            self.assertIn(sig, hidden)

    def test_templates_and_constraints(self):
        a = self.one("rmp::Widget::as")
        self.assertEqual((a.template, a.signature), ("template <class T> requires(sizeof(T) > 1)", "T &as()"))

    def test_operators_static_and_detail(self):
        self.assertEqual(self.one("rmp::Widget::operator bool").signature, "explicit operator bool() const")
        self.assertEqual(self.one("rmp::Widget::operator==").signature,
                         "bool operator==(const Widget &other) const")
        self.assertTrue(self.one("rmp::Widget::current").static)
        self.assertTrue(self.one("rmp::Widget::detail_tick").internal)

    def test_a_title_line_names_a_group_and_documents_nothing(self):
        margin = self.one("rmp::Widget::margin")
        self.assertEqual((margin.group, margin.doc, margin.covered), ("Sizes", "", False))

    def test_private_is_not_api(self):
        self.assertNotIn("rmp::Widget::_hidden", self.by)

    def test_enums(self):
        fast, slow, off = (self.one(f"rmp::Mode::{n}") for n in ("FAST", "SLOW", "OFF"))
        self.assertEqual((fast.trailing, slow.doc, off.value), ("as fast as it goes", "Slowly, with care.", "4"))
        self.assertEqual([c.name for c in self.one("rmp::Flat").children], ["A", "B", "C"])

    def test_a_string_with_braces_and_semicolons(self):
        name = self.one("rmp::Options::name")
        self.assertEqual((name.value, name.trailing), ('"a; b { c }"', "braces and semicolons in a string"))

    def test_a_nested_class_defined_outside(self):
        inner = self.one("rmp::Outer::Inner")
        self.assertIs(inner.parent, self.one("rmp::Outer"))
        self.assertEqual(self.one("rmp::Outer::Inner::go").doc, "Its one method.")

    def test_detail_namespace_is_internal(self):
        self.assertTrue(self.one("rmp::detail::Secret").internal)

    def test_alias_constant_and_out_of_line_body(self):
        self.assertEqual(self.one("rmp::Number").signature, "using Number = double")
        limit = self.one("rmp::LIMIT")
        self.assertEqual((limit.kind, limit.value, limit.trailing), ("constant", "8", "the most there can be"))
        self.assertEqual(len(self.by["rmp::Widget::as"]), 1, "the body outside the class is not a second entity")

    def test_an_unnamed_struct_is_its_field(self):
        ours = self.one("rmp::Options::ours")
        self.assertEqual((ours.kind, ours.signature), ("field", "struct { … } ours"))
        self.assertEqual(ours.doc, "What it keeps. One unnamed struct and its one field.")
        self.assertNotIn("rmp::Options::struct", self.by)

    def test_a_macro_in_two_branches(self):
        m = self.one("RMP_ENTRY")
        self.assertEqual(m.signature, "#define RMP_ENTRY(X)")
        self.assertEqual(m.doc, "The entry point, per platform.")
        self.assertEqual(m.branches, [("#if defined(PLATFORM_WEB)", "web_entry(X)"), ("#else", "desktop_entry(X)")])


class FrameworkHeadersTest(unittest.TestCase):
    """Every header of the framework reads, without an error."""

    def test_every_header_reads(self):
        fw = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))
        headers = sorted((fw / "include" / "rmp").glob("*.h"))
        if not headers:
            self.skipTest("no framework checkout next to rmp-docs")
        for h in headers:
            with self.subTest(header=h.name):
                root = read_header(f"include/rmp/{h.name}", h.read_text(encoding="utf-8"))
                self.assertTrue(root.doc, f"{h.name} has no file block")


if __name__ == "__main__":
    unittest.main()
