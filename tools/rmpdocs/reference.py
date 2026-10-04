"""The reference: pages generated from include/rmp/*.h at FRAMEWORK_REF.

Nothing in these pages is typed by hand. A signature is the header's, a
sentence is the header's comment, a line number is where the declaration is.
The only hand-written input is reference.toml: which entity gets a page of its
own, and the decisions (hide, allow_undocumented) that each carry a reason.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import prose
from .cxx import Entity, read_header
from .highlight import highlight


@dataclass
class RefPage:
    url: str
    entity: Entity
    title: str
    description: str
    body: str = ""
    anchors: dict = field(default_factory=dict)    # qualname -> anchor id


def page_url(qualname: str) -> str:
    return "reference/" + qualname.replace("::", "-") + ".html"


def anchor_id(name: str) -> str:
    if name.startswith("operator"):
        table = {"==": "eq", "!=": "ne", "[]": "index", "()": "call", "=": "assign",
                 "<": "lt", ">": "gt", "+": "plus", "-": "minus", "*": "times", "/": "div"}
        rest = name[len("operator"):].strip()
        return "operator-" + table.get(rest, re.sub(r"[^\w]+", "-", rest).strip("-") or "op")
    return re.sub(r"[^\w-]+", "-", name.lstrip("~")).strip("-") or "x"


class Reference:
    def __init__(self, framework: Path, config: dict):
        self.framework = framework
        self.config = config
        self.headers: dict[str, Entity] = {}
        self.pages: list[RefPage] = []
        self.index: dict[str, str] = {}       # qualname -> url#anchor

    def read(self):
        for h in sorted((self.framework / "include" / "rmp").glob("*.h")):
            rel = f"include/rmp/{h.name}"
            self.headers[rel] = read_header(rel, h.read_text(encoding="utf-8"))
        return self

    def entities(self):
        for root in self.headers.values():
            for e in root.walk():
                if e.kind != "file":
                    yield e

    def find(self, qualname: str) -> Entity | None:
        return next((e for e in self.entities() if e.qualname == qualname
                     and e.kind in ("class", "struct", "namespace", "enum")), None)

    def build(self, ref_url_for_line) -> list[RefPage]:
        """Pages for every entity reference.toml names."""
        self.ref_url_for_line = ref_url_for_line
        for qualname in self.config.get("pages", {}).get("classes", []):
            ent = self.find(qualname)
            if ent is None:
                raise KeyError(f"reference.toml names {qualname}, which no header declares")
            page = RefPage(page_url(qualname), ent, qualname,
                           prose.first_sentence(ent.doc) or f"{ent.kind} {qualname}")
            self.pages.append(page)
            self._index_page(page)
        for page in self.pages:
            page.body = self.render_type(page)
        return self.pages

    def _index_page(self, page: RefPage):
        self.index[page.entity.qualname] = page.url
        for c in page.entity.public_children():
            self.index.setdefault(c.qualname, f"{page.url}#{anchor_id(c.name)}")

    # -- links inside comments -------------------------------------------------

    def link(self, current_url: str):
        """A function for prose.inline: the URL of a name a comment mentions,
        relative to the page it is on, or None."""
        def resolve(code: str):
            name = re.sub(r"\(.*\)$", "", code.strip())
            name = re.sub(r"<.*>$", "", name)
            target = self.index.get(name)
            if target is None:
                return None
            if target.startswith(current_url + "#"):
                return target[len(current_url):]
            return "/" + target
        return resolve

    # -- a class or struct page -------------------------------------------------

    def render_type(self, page: RefPage) -> str:
        e = page.entity
        link = self.link(page.url)
        out = []
        out.append(f'<h1><code>{html.escape(e.qualname)}</code></h1>')
        out.append(self.meta(e, kind=e.kind, include=True))
        if e.signature:
            sig = (e.template + "\n" if e.template else "") + e.signature
            out.append(f'<div class="signature">{highlight(sig, "cpp")}</div>')
        if e.doc:
            out.append(prose.to_html(e.doc, link))

        members = [c for c in e.public_children()]
        groups: list[tuple[str, str, list[Entity]]] = []
        for m in members:
            if not groups or groups[-1][0] != m.group:
                groups.append((m.group, m.group_doc, []))
            groups[-1][2].append(m)
        for title, intro, items in groups:
            if title:
                gid = "group-" + re.sub(r"[^\w]+", "-", title.lower()).strip("-")[:48]
                out.append(f'<h2 id="{gid}">{prose.inline(title, link)}</h2>')
                rest = intro.split("\n", 1)[1] if "\n" in intro else ""
                if rest.strip():
                    out.append(prose.to_html(rest.strip("\n"), link))
            for block in self.runs(items):
                out.append(self.render_block(block, link))
        return "\n".join(x for x in out if x)

    def runs(self, items: list[Entity]) -> list[list[Entity]]:
        """Members shown together: a run that shares one doc, and overloads."""
        blocks: list[list[Entity]] = []
        for m in items:
            if blocks and (m.run_doc and not m.doc or m.name == blocks[-1][-1].name):
                blocks[-1].append(m)
            else:
                blocks.append([m])
        return blocks

    def render_block(self, block: list[Entity], link) -> str:
        first = block[0]
        names = []
        for m in block:
            if m.name not in names:
                names.append(m.name)
        ids = [anchor_id(n) for n in names]
        title = ", ".join(f"<code>{html.escape(n)}</code>" for n in names)
        out = [f'<section class="entity" id="{ids[0]}">']
        for extra in ids[1:]:
            out.append(f'<span id="{extra}"></span>')
        out.append(f"<h3>{title}</h3>")
        for m in block:
            sig = m.signature
            if m.kind in ("field", "constant") and m.value:
                sig = f"{sig} = {m.value}" if not m.value.startswith("{") else f"{sig}{m.value}"
            if m.template:
                sig = m.template + "\n" + sig
            out.append(f'<div class="signature">{highlight(sig, "cpp")}</div>')
        out.append(self.meta(first, kind=_kind_label(first)))
        doc = first.doc
        if doc:
            out.append(prose.to_html(doc, link))
        for m in block:
            if m.trailing:
                prefix = f"<code>{html.escape(m.name)}</code>: " if len(block) > 1 else ""
                out.append(f"<p>{prefix}{prose.inline(m.trailing[0].upper() + m.trailing[1:], link)}</p>")
        out.append("</section>")
        return "\n".join(out)

    def meta(self, e: Entity, kind: str, include: bool = False) -> str:
        parts = [f'<span class="badge">{html.escape(kind)}</span>']
        if include:
            parts.append(f"<code>#include &lt;{html.escape(e.header.removeprefix('include/'))}&gt;</code>")
        url = self.ref_url_for_line(e.header, e.line, e.end_line or e.line)
        parts.append(f'<a href="{html.escape(url)}">{html.escape(e.header)}:{e.line}</a>')
        return f'<div class="entity-meta">{" ".join(parts)}</div>'


def _kind_label(e: Entity) -> str:
    if e.kind == "function":
        if e.name.startswith("_"):
            return "hook"
        return "static function" if e.static else "function"
    return e.kind
