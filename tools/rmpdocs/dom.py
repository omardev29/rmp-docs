"""A small, strict HTML tree: enough to read the site's fragments, change them
and write them back out.

Strict on purpose. A fragment with an unclosed <p> or a </div> that closes the
wrong element is an error with a line number, not something a browser quietly
repairs -- because the repair is a guess, and the page that ships is the guess.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}
# An element's and an attribute's name, as the parser gives them (lower
# case): what HTML, SVG and custom elements are spelled with -- `my-widget`,
# `data-x`, `xlink:href`. A tag starts with a letter, or it is not a tag:
# `<_>` is text to a browser, and `</_>` a comment.
TAG = re.compile(r"[a-z][a-z0-9_:.\-]*\Z")
NAME = re.compile(r"[a-z_:][a-z0-9_:.\-]*\Z")
# Elements whose text is never touched by a transform (code, scripts, styles).
RAW_TEXT = {"script", "style"}
# Elements whose content is text and nothing else, to a browser and to the
# parser: inside them `<b>` is four characters, not an element.
TEXT_ONLY = RAW_TEXT | {"textarea", "title"}


class Node:
    __slots__ = ("tag", "attrs", "children", "line", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, children=None, line: int = 0):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children = list(children or [])
        self.line = line
        self.parent = None
        for c in self.children:
            c.parent = self

    def append(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def text(self) -> str:
        out = []
        for c in self.children:
            out.append(c.text() if isinstance(c, Node) else c.data if isinstance(c, Text) else "")
        return "".join(out)

    def walk(self):
        """Every element below this one, depth first, this one included."""
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def __repr__(self):
        return f"<{self.tag} {self.attrs} line={self.line}>"


class Text:
    __slots__ = ("data", "parent", "line")

    def __init__(self, data: str, line: int = 0):
        self.data = data
        self.parent = None
        self.line = line

    def text(self) -> str:
        return self.data


class Comment:
    __slots__ = ("data", "parent", "line")

    def __init__(self, data: str, line: int = 0):
        self.data = data
        self.parent = None
        self.line = line

    def text(self) -> str:
        return ""


class Raw:
    """Already-serialised HTML, inserted as is (highlighted code, generated
    markup). Never parsed again."""
    __slots__ = ("html", "parent", "line")

    def __init__(self, markup: str, line: int = 0):
        self.html = markup
        self.parent = None
        self.line = line

    def text(self) -> str:
        return ""


class HtmlError(Exception):
    def __init__(self, line: int, message: str):
        super().__init__(line, message)
        self.line = line
        self.message = message

    def __str__(self):
        return f"line {self.line}: {self.message}"


class _Builder(HTMLParser):
    def __init__(self, first_line: int = 1):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]
        self.errors: list[HtmlError] = []
        self.shift = first_line - 1

    def _line(self) -> int:
        """The line in the file, not in the fragment: what every node, every
        error and every message that names another line says."""
        return self.getpos()[0] + self.shift

    def _node(self, tag, attrs) -> Node:
        """The element of a start tag, and what is wrong with how it is
        written: a name a browser reads but nobody meant (`<p/<p id=x>` gives
        <p> an attribute called `<p`), a `<` outside the quotes (`<img src=x`
        with its `>` forgotten takes the next tag in as its value), an
        attribute twice."""
        line = self._line()
        raw = self.get_starttag_text() or ""
        if "<" in re.sub(r"\"[^\"]*\"|'[^']*'", "", raw[1:]):
            self.errors.append(HtmlError(line, f"{raw[:40]!r}: a < inside a tag, where a quote or "
                                               "a > is missing"))
        if not TAG.match(tag):
            self.errors.append(HtmlError(line, f"<{tag[:40]}> is not an element's name"))
        seen = {}
        for k, v in attrs:
            if not NAME.match(k):
                self.errors.append(HtmlError(line, f"<{tag}> has an attribute called {k[:40]!r}"))
            if k in seen:
                self.errors.append(HtmlError(line, f"<{tag}> has the attribute {k!r} twice"))
            seen[k] = "" if v is None else v
        return Node(tag, seen, line=line)

    def handle_starttag(self, tag, attrs):
        node = self._node(tag, attrs)
        self.stack[-1].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = self._node(tag, attrs)
        line = node.line
        self.stack[-1].append(node)
        node.attrs["/"] = ""  # written self-closed: written back the same way
        # Self-closing is SVG's own syntax (foreign content); in HTML it is a
        # mistake the browser silently ignores, leaving the element open.
        if tag not in VOID and not any(n.tag == "svg" for n in self.stack) and tag != "svg":
            self.errors.append(HtmlError(line, f"<{tag}/> is not a void element; close it"))

    def handle_endtag(self, tag):
        line = self._line()
        if tag in VOID:
            self.errors.append(HtmlError(line, f"</{tag}>: {tag} is a void element"))
            return
        if len(self.stack) == 1:
            self.errors.append(HtmlError(line, f"</{tag}> closes nothing"))
            return
        top = self.stack[-1]
        if top.tag != tag:
            self.errors.append(HtmlError(
                line, f"</{tag}> closes <{top.tag}> opened on line {top.line}"))
            # Recover by popping to the matching element if there is one.
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i].tag == tag:
                    del self.stack[i:]
                    return
            return
        self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].append(Text(data, self._line()))

    def handle_comment(self, data):
        self.stack[-1].append(Comment(data, self._line()))

    def handle_decl(self, decl):
        # `<!doctype html>`, before everything, is the one declaration HTML
        # has; anything else -- `<!DOCTYPE` with the rest of a page in it, a
        # doctype inside an element -- is markup the browser ignores.
        if " ".join(decl.lower().split()) != "doctype html" or len(self.stack) > 1 or \
                any(not (isinstance(c, Text) and not c.data.strip()) for c in self.root.children):
            self.errors.append(HtmlError(self._line(), f"<!{decl[:40]}> is not <!doctype html> "
                                                           "at the start: a browser ignores it"))
        self.stack[-1].append(Raw(f"<!{decl}>", self._line()))

    def unknown_decl(self, data):
        self.errors.append(HtmlError(self._line(), f"unknown declaration {data!r}"))

    # The two ways the parser reads markup that is not markup -- as a browser
    # does, and as a browser does, without a word. `</ p>`, `</<p>` and `<!x>`
    # are comments to it ("bogus" ones), and `</>` is nothing at all.
    def parse_bogus_comment(self, i, report=1):
        end = super().parse_bogus_comment(i, report)
        if report and end > i:
            self.errors.append(HtmlError(self._line(), f"{self.rawdata[i:end][:40]!r} is not a tag: "
                                                           "a browser reads it as a comment"))
        return end

    def parse_endtag(self, i):
        if self.rawdata.startswith("</>", i) and getattr(self, "cdata_elem", None) is None:
            self.errors.append(HtmlError(self._line(), "</> closes nothing: a browser drops it"))
        return super().parse_endtag(i)

    def handle_pi(self, data):
        # The parser drops one without a word; a browser reads it as a comment.
        self.errors.append(HtmlError(self._line(), f"<?{data[:40]}> is a processing "
                                                       "instruction, and HTML has none"))


def parse(markup: str, first_line: int = 1) -> tuple[Node, list[HtmlError]]:
    """The tree and every well-formedness problem found, by line."""
    b = _Builder(first_line)
    b.feed(markup)
    # What the parser has not read once it has every byte is markup it is
    # still waiting to see end: an attribute's quote, a tag's >, a comment's
    # -->. close() then drops it, or makes a guess of it, without a word --
    # and the page loses everything from there on.
    if b.rawdata.startswith("<") and getattr(b, "cdata_elem", None) is None:
        b.errors.append(HtmlError(b._line(), f"{b.rawdata[:40]!r} never ends: markup needs its "
                                                 "closing >, and a < that is text is &lt;"))
    b.close()
    for open_node in b.stack[1:]:
        b.errors.append(HtmlError(open_node.line, f"<{open_node.tag}> is never closed"))
    return b.root, b.errors


def escape(s: str) -> str:
    return html.escape(s, quote=False)


def attr_escape(s: str) -> str:
    return html.escape(s, quote=True)


def comment_says_otherwise(data: str) -> bool:
    """A comment whose text, between <!-- and -->, a browser reads as
    something else. `<!-->` and `<!--->` are whole comments to a browser, the
    first `-->` or `--!>` ends one -- what follows is on the page -- and a
    text ending in `<!-` meets the `-->` after it as `<!---->`. (HTML's rule
    also forbids `<!--` inside, but a browser reads that one as written.)"""
    return (data.startswith((">", "->")) or "-->" in data or "--!>" in data
            or data.endswith("<!-"))


def serialize(node, out=None) -> str:
    """The HTML of a node and everything under it. It never writes markup
    that reads back as something else: what cannot be written -- a comment
    a browser would end early, an element inside a <script>, a script that
    says </script> or <!-- -- is an HtmlError naming the line, not a page
    that ships the browser's guess."""
    top = out is None
    out = [] if top else out
    if isinstance(node, Text):
        parent = node.parent
        if parent is not None and parent.tag in RAW_TEXT:
            if f"</{parent.tag}" in node.data.lower():
                raise HtmlError(node.line or parent.line,
                                f"the text of a <{parent.tag}> cannot say </{parent.tag}>: "
                                f"it would end there")
            if parent.tag == "script" and "<!--" in node.data:
                # After `<!--<script` a browser reads the next </script> as
                # script too, and the page after it -- html.parser does not.
                # The HTML standard's own advice: write it `\x3C!--`.
                raise HtmlError(node.line or parent.line,
                                "the text of a <script> cannot say <!--: after <!--<script a browser "
                                "reads past </script> (write \\x3C!-- instead)")
            out.append(node.data)
        else:
            out.append(escape(node.data))
    elif isinstance(node, Comment):
        if comment_says_otherwise(node.data):
            raise HtmlError(node.line, f"<!--{node.data[:40]}--> cannot be written as a comment: "
                                       "a browser would end it early")
        out.append(f"<!--{node.data}-->")
    elif isinstance(node, Raw):
        out.append(node.html)
    elif node.tag == "#root":
        for c in node.children:
            serialize(c, out)
    else:
        wrong = node.tag if not TAG.match(node.tag) else \
            next((a for a in node.attrs if a != "/" and not NAME.match(a)), None)
        if wrong is not None:
            raise HtmlError(node.line, f"{wrong[:40]!r} cannot be written as the name of an element "
                                       "or an attribute")
        attrs = "".join(f" {k}" if v == "" and k in BOOLEAN_ATTRS else f' {k}="{attr_escape(v)}"'
                        for k, v in node.attrs.items() if k != "/")
        if "/" in node.attrs:
            if node.children:
                raise HtmlError(node.line, f"<{node.tag}/> is written self-closed: it holds nothing")
            up = node
            while up is not None and up.tag != "svg":
                up = up.parent
            if node.tag not in VOID and up is None:
                # What parse() refuses: outside an svg, a browser leaves it open.
                raise HtmlError(node.line, f"<{node.tag}/> is not a void element; close it")
            out.append(f"<{node.tag}{attrs}/>")
            return "".join(out) if top else ""
        out.append(f"<{node.tag}{attrs}>")
        if node.tag in TEXT_ONLY:
            other = next((c for c in node.children if not isinstance(c, Text)), None)
            if other is not None:
                raise HtmlError(getattr(other, "line", 0) or node.line,
                                f"<{node.tag}> holds text and nothing else")
        if node.tag in VOID and node.children:
            raise HtmlError(node.line, f"<{node.tag}> is a void element: it holds nothing")
        if node.tag not in VOID:
            for c in node.children:
                serialize(c, out)
            out.append(f"</{node.tag}>")
    return "".join(out) if top else ""


BOOLEAN_ATTRS = {"hidden", "open", "defer", "async", "disabled", "checked", "selected",
                 "autofocus", "required", "readonly", "multiple", "novalidate", "inert",
                 "allowfullscreen", "nomodule", "playsinline", "muted", "controls", "loop"}


def el(tag: str, attrs: dict | None = None, *children) -> Node:
    """Build an element: el("a", {"href": "x"}, "text", el("b", None, "bold"))."""
    node = Node(tag, attrs or {})
    for c in children:
        if isinstance(c, str):
            node.append(Text(c))
        elif c is not None:
            node.append(c)
    return node
