"""tools/rmpdocs/dom.py held to its promises for ANY markup and ANY tree.

  parse()      total: whatever the text, a tree and a list of HtmlErrors,
               never an exception.
  serialize()  what it writes reads back, through parse(), as the tree it
               was given -- or it refuses with an HtmlError naming the line.
               It never writes markup that means something else: the site
               ships what serialize() wrote, and a browser reads it.
  the two      a fragment parse() takes without an error, written back out,
               reads back as the same tree, and writing it again changes
               nothing.
  escape()     text and attribute values come back exactly through the
               parser, whatever is in them.

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

dom = load("dom")

# Anything a text node or an attribute value may hold, leaning on what HTML
# itself turns on.
DECISIVE = st.sampled_from(list("<>&\"'/=!-?;# \n\t\r") + [
    "&amp;", "&lt;", "&#60;", "&#x3c;", "&notit;", "&", "<!--", "-->", "--!>", "<!-", "->",
    "</script", "</SCRIPT>", "</style >", "<script>", "</p>", "<p>", "<b>", "<![CDATA[", "]]>",
    "<?", "?>", "<!DOCTYPE html>", "</", "<br/>", "\x00", " ", "﻿"])
TEXT = st.lists(st.one_of(DECISIVE, st.characters(exclude_categories=("Cs",))), max_size=24).map("".join)

ELEMENTS = ["div", "p", "span", "a", "code", "pre", "ul", "li", "h2", "table", "td", "section",
            "details", "summary", "button", "svg", "path", "textarea", "title", "script", "style"]
ATTRIBUTE = st.sampled_from(["class", "id", "href", "title", "data-lang", "hidden", "open",
                             "aria-label", "d", "viewBox", "src"])
ATTRS = st.dictionaries(ATTRIBUTE.map(str.lower), st.one_of(st.just(""), TEXT), max_size=3)
# What a transform could name an attribute: anything at all.
ANY_ATTRS = st.dictionaries(st.one_of(ATTRIBUTE.map(str.lower), st.text(min_size=1, max_size=6)),
                            st.one_of(st.just(""), TEXT), max_size=3)


def tree(children):
    return st.builds(lambda tag, attrs, kids: dom.el(tag, attrs, *kids),
                     st.one_of(st.sampled_from(ELEMENTS), st.sampled_from(ELEMENTS),
                               st.text(min_size=1, max_size=4)),
                     st.one_of(ATTRS, ATTRS, ANY_ATTRS), st.lists(children, max_size=4))


def leaf():
    return st.one_of(
        TEXT.filter(bool),
        st.builds(lambda tag, attrs: dom.el(tag, attrs), st.sampled_from(sorted(dom.VOID)), ATTRS),
        TEXT.map(dom.Comment),
    )


NODE = st.recursive(leaf(), lambda kids: tree(kids), max_leaves=12)
ROOT = st.lists(NODE, max_size=5).map(lambda kids: dom.el("#root", None, *kids))

# The ordinary: elements, attributes and text, nothing a browser reads as
# text only, and no comment -- what serialize() must always write.
ORDINARY = st.recursive(
    st.one_of(TEXT.filter(bool),
              st.builds(lambda tag, attrs: dom.el(tag, attrs), st.sampled_from(sorted(dom.VOID)), ATTRS)),
    lambda kids: st.builds(lambda tag, attrs, k: dom.el(tag, attrs, *k),
                           st.sampled_from([e for e in ELEMENTS if e not in ("script", "style", "textarea", "title")]),
                           ATTRS, st.lists(kids, max_size=4)),
    max_leaves=12).map(lambda node: dom.el("#root", None, node))


def shape(node):
    """A tree as plain data, adjacent text merged, empty text dropped: what
    two trees that serialize the same have in common."""
    if isinstance(node, dom.Text):
        return ("text", node.data)
    if isinstance(node, dom.Comment):
        return ("comment", node.data)
    if isinstance(node, dom.Raw):
        return ("raw", node.html)
    kids = []
    for c in node.children:
        s = shape(c)
        if s[0] == "text" and kids and kids[-1][0] == "text":
            kids[-1] = ("text", kids[-1][1] + s[1])
        elif s != ("text", ""):
            kids.append(s)
    return (node.tag, dict(node.attrs), kids)


def written(root) -> str | None:
    """serialize(root), or None when it refused -- with an HtmlError, the
    one way it may."""
    try:
        return dom.serialize(root)
    except dom.HtmlError:
        return None


class SerializeTest(unittest.TestCase):

    @given(ROOT)
    def test_what_it_writes_reads_back_as_the_tree_or_it_refuses(self, root):
        out = written(root)
        if out is None:
            return
        again, errors = dom.parse(out)
        self.assertEqual([str(e) for e in errors], [], out)
        self.assertEqual(shape(again), shape(root), out)

    @given(ORDINARY)
    def test_the_ordinary_is_always_written(self, root):
        out = dom.serialize(root)
        again, errors = dom.parse(out)
        self.assertEqual(errors, [])
        self.assertEqual(shape(again), shape(root))

    @given(st.sampled_from(["script", "style", "textarea", "title"]),
           st.lists(st.one_of(st.sampled_from("&>\"' x"),
                              st.characters(exclude_characters="<", exclude_categories=("Cs",)))).map("".join),
           st.text(alphabet=st.characters(exclude_characters="<->", exclude_categories=("Cs",))))
    def test_a_script_with_no_tag_in_it_and_a_comment_with_no_dash_are_written(self, tag, text, said):
        root = dom.el("#root", None, dom.el(tag, None, text))
        root.append(dom.Comment(said))
        again, errors = dom.parse(dom.serialize(root))
        self.assertEqual(errors, [])
        self.assertEqual(shape(again), shape(root))

    @given(st.sampled_from(["script", "style"]), TEXT)
    def test_a_script_s_text_is_written_as_it_is_or_refused(self, tag, text):
        out = written(dom.el("div", None, dom.el(tag, None, text)))
        if out is not None:
            self.assertEqual(out, f"<div><{tag}>{text}</{tag}></div>")
            again, errors = dom.parse(out)
            self.assertEqual(errors, [])
            self.assertEqual(shape(again), shape(dom.el("#root", None, dom.el("div", None, dom.el(tag, None, text)))))

    @given(TEXT)
    def test_a_comment_is_written_as_it_is_or_refused(self, data):
        root = dom.el("#root")
        root.append(dom.Comment(data))
        out = written(root)
        if out is not None:
            again, errors = dom.parse(out)
            self.assertEqual(errors, [])
            self.assertEqual(shape(again), ("#root", {}, [("comment", data)]), out)


# Markup, whole and in pieces: what a page's author writes, and the mistakes.
FRAGMENT = st.lists(st.one_of(TEXT, st.sampled_from(
    ["<p>", "</p>", "<div class='a'>", "</div>", "<br>", "<b>", "</b>", "<!-- c -->",
     "<script>", "</script>", "<pre>", "</pre>", '<a href="x">', "</a>", "<a href='", '<a title="',
     "<p", "</p", "<!--", "<!DOCTYPE", "<?x?>", "<?php", "<", "</", "<!x", "<![CDATA[", "<img src=x",
     "<svg>", "</svg>", "<path d='m'/>", "<p/>", "<br/>", "<!doctype html>", "\n", "<p class=a class=b>"])),
    max_size=12).map("".join)
END = '<p id="end">end</p>'


class ParseTest(unittest.TestCase):

    @given(st.one_of(TEXT, st.text()))
    def test_any_text_is_a_tree_and_a_list_of_errors(self, text):
        root, errors = dom.parse(text)
        self.assertEqual(root.tag, "#root")
        self.assertTrue(all(isinstance(e, dom.HtmlError) for e in errors))

    @given(FRAGMENT)
    def test_a_fragment_it_takes_writes_back_to_the_same_tree(self, text):
        root, errors = dom.parse(text)
        if errors:
            return
        out = written(root)
        if out is None:
            return
        again, errors = dom.parse(out)
        self.assertEqual([str(e) for e in errors], [], out)
        self.assertEqual(shape(again), shape(root), out)
        self.assertEqual(dom.serialize(again), out)


    @given(FRAGMENT)
    def test_nothing_before_a_whole_element_takes_it_unsaid(self, text):
        """Whatever comes first, the element after it is read as itself, or
        there is an error: markup that never ends swallows the rest of the
        page, and the parser it is built on drops it without a word."""
        root, errors = dom.parse(text + END)
        if not errors:
            self.assertEqual(shape(root)[2][-1:], [("p", {"id": "end"}, [("text", "end")])], written(root))


    @given(FRAGMENT, st.integers(1, 500))
    def test_a_fragment_further_down_a_file_is_the_same_fragment_further_down(self, text, first):
        root, errors = dom.parse(text)
        moved, moved_errors = dom.parse(text, first)

        def further(message):   # a message that names another line names it in the file too
            return re.sub(r"on line (\d+)", lambda m: f"on line {int(m.group(1)) + first - 1}", message)

        self.assertEqual([(e.line + first - 1, further(e.message)) for e in errors],
                         [(e.line, e.message) for e in moved_errors])
        self.assertEqual([str(e) for e in moved_errors], [f"line {e.line}: {e.message}" for e in moved_errors])
        def everything(node):   # every node, text and comments included
            return [node] + [d for c in getattr(node, "children", []) for d in everything(c)]
        self.assertEqual([n.line + first - 1 for n in everything(root)][1:],
                         [n.line for n in everything(moved)][1:])


class NodeTest(unittest.TestCase):

    @given(ORDINARY)
    def test_text_is_every_text_node_in_order(self, root):
        def texts(node):
            return "".join(c.data if isinstance(c, dom.Text) else texts(c) if isinstance(c, dom.Node) else ""
                           for c in node.children)
        self.assertEqual(root.text(), texts(root))
        again, _errors = dom.parse(dom.serialize(root))
        self.assertEqual(again.text(), root.text())

    @given(ROOT)
    def test_walk_is_every_element_once_depth_first(self, root):
        def elements(node):
            return [node] + [e for c in node.children if isinstance(c, dom.Node) for e in elements(c)]
        self.assertEqual(list(root.walk()), elements(root))
        for node in root.walk():
            self.assertEqual(node.classes(), (node.attrs.get("class") or "").split())
            self.assertEqual(node.get("class", "none"), node.attrs.get("class", "none"))
            for c in node.children:
                self.assertIs(c.parent, node)
                self.assertEqual(c.text() if not isinstance(c, dom.Node) else "",
                                 c.data if isinstance(c, dom.Text) else "")


class EscapeTest(unittest.TestCase):

    @given(TEXT)
    def test_text_comes_back_exactly(self, text):
        self.assertNotIn("<", dom.escape(text))
        self.assertEqual(html.unescape(dom.escape(text)), text)
        root, errors = dom.parse(f"<p>{dom.escape(text)}</p>")
        self.assertEqual(errors, [])
        self.assertEqual(root.children[0].text(), text)

    @given(TEXT)
    def test_an_attribute_value_comes_back_exactly(self, value):
        self.assertNotIn('"', dom.attr_escape(value))
        root, errors = dom.parse(f'<p title="{dom.attr_escape(value)}"></p>')
        self.assertEqual(errors, [])
        self.assertEqual(root.children[0].get("title"), value)


if __name__ == "__main__":
    unittest.main()
