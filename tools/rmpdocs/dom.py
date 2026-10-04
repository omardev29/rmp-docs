"""A small, strict HTML tree: enough to read the site's fragments, change them
and write them back out.

Strict on purpose. A fragment with an unclosed <p> or a </div> that closes the
wrong element is an error with a line number, not something a browser quietly
repairs -- because the repair is a guess, and the page that ships is the guess.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}
# Elements whose text is never touched by a transform (code, scripts, styles).
RAW_TEXT = {"script", "style"}


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
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]
        self.errors: list[HtmlError] = []

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        seen = {}
        for k, v in attrs:
            if k in seen:
                self.errors.append(HtmlError(line, f"<{tag}> has the attribute {k!r} twice"))
            seen[k] = "" if v is None else v
        node = Node(tag, seen, line=line)
        self.stack[-1].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        line = self.getpos()[0]
        node = Node(tag, {k: ("" if v is None else v) for k, v in attrs}, line=line)
        self.stack[-1].append(node)
        node.attrs["/"] = ""  # written self-closed: written back the same way
        # Self-closing is SVG's own syntax (foreign content); in HTML it is a
        # mistake the browser silently ignores, leaving the element open.
        if tag not in VOID and not any(n.tag == "svg" for n in self.stack) and tag != "svg":
            self.errors.append(HtmlError(line, f"<{tag}/> is not a void element; close it"))

    def handle_endtag(self, tag):
        line = self.getpos()[0]
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
        self.stack[-1].append(Text(data, self.getpos()[0]))

    def handle_comment(self, data):
        self.stack[-1].append(Comment(data, self.getpos()[0]))

    def handle_decl(self, decl):
        self.stack[-1].append(Raw(f"<!{decl}>", self.getpos()[0]))

    def unknown_decl(self, data):
        self.errors.append(HtmlError(self.getpos()[0], f"unknown declaration {data!r}"))


def parse(markup: str, first_line: int = 1) -> tuple[Node, list[HtmlError]]:
    """The tree and every well-formedness problem found, by line."""
    b = _Builder()
    b.feed(markup)
    b.close()
    for open_node in b.stack[1:]:
        b.errors.append(HtmlError(open_node.line, f"<{open_node.tag}> is never closed"))
    if first_line != 1:
        shift = first_line - 1
        for n in b.root.walk():
            n.line += shift
        for e in b.errors:
            e.line += shift
    return b.root, b.errors


def escape(s: str) -> str:
    return html.escape(s, quote=False)


def attr_escape(s: str) -> str:
    return html.escape(s, quote=True)


def serialize(node, out=None) -> str:
    top = out is None
    out = [] if top else out
    if isinstance(node, Text):
        parent = node.parent
        if parent is not None and parent.tag in RAW_TEXT:
            out.append(node.data)
        else:
            out.append(escape(node.data))
    elif isinstance(node, Comment):
        out.append(f"<!--{node.data}-->")
    elif isinstance(node, Raw):
        out.append(node.html)
    elif node.tag == "#root":
        for c in node.children:
            serialize(c, out)
    else:
        attrs = "".join(f" {k}" if v == "" and k in BOOLEAN_ATTRS else f' {k}="{attr_escape(v)}"'
                        for k, v in node.attrs.items() if k != "/")
        if "/" in node.attrs:
            out.append(f"<{node.tag}{attrs}/>")
            return "".join(out) if top else ""
        out.append(f"<{node.tag}{attrs}>")
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
