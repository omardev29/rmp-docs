"""The reference: pages generated from include/rmp/*.h at FRAMEWORK_REF.

Nothing in these pages is typed by hand. A signature is the header's, a
sentence is the header's comment, a line number is where the declaration is.
The only hand-written input is reference.toml: which internal entity is shown
anyway (and as what), and the decisions that each carry a reason.

The pages:

    reference/namespaces/<ns>.html   a namespace: its functions, enums,
                                     constants, and the small structs inline
    reference/classes/<T>.html       a class or struct with methods of its own
    reference/behaviors/<B>.html     each behavior in rmp::behavior
    reference/macros.html            the macros a game uses

A struct with fewer than two methods of its own is a table on its namespace's
page, not a page: an options struct is read next to the function that takes it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import prose
from .cxx import Entity, read_header
from .highlight import highlight

HOOKS = {"_ready", "_update", "_late_update", "_draw", "_collision", "_end", "_suspend", "_resume"}
OWN_PAGE_MIN_FUNCTIONS = 2


@dataclass
class RefPage:
    url: str
    title: str
    description: str
    kind: str                       # namespace class behavior macros index
    entities: list = field(default_factory=list)
    body: str = ""
    nav_title: str = ""
    order: float = 100
    source: str = ""
    line: int = 0


def anchor_id(name: str) -> str:
    if name.startswith("operator"):
        table = {"==": "eq", "!=": "ne", "[]": "index", "()": "call", "=": "assign",
                 "<": "lt", ">": "gt", "+": "plus", "-": "minus", "*": "times", "/": "div"}
        rest = name[len("operator"):].strip()
        return "operator-" + table.get(rest, re.sub(r"[^\w]+", "-", rest).strip("-") or "op")
    return re.sub(r"[^\w-]+", "-", name.lstrip("~")).strip("-") or "x"


def slug_q(qualname: str) -> str:
    return qualname.replace("::", "-")


EXPOSED: set[str] = set()   # reference.toml [expose]: shown although internal


def hidden(e: Entity) -> bool:
    """Not API: internal, private, deleted, or inside something that is --
    unless reference.toml exposes it or what it is inside."""
    while e is not None and e.kind != "file":
        if e.qualname in EXPOSED:
            return e.deleted
        if e.internal or e.deleted:
            return True
        e = e.parent
    return False


class Reference:
    def __init__(self, framework: Path, config: dict):
        self.framework = framework
        self.config = config
        self.headers: dict[str, Entity] = {}
        self.pages: list[RefPage] = []
        self.index: dict[str, str] = {}       # qualname -> url[#anchor]
        self.expose = {k: v for k, v in config.get("expose", {}).items()}
        EXPOSED.clear()
        EXPOSED.update(self.expose)
        self.hide = config.get("hide", {})

    # -- reading -------------------------------------------------------------

    def read(self):
        for h in sorted((self.framework / "include" / "rmp").glob("*.h")):
            rel = f"include/rmp/{h.name}"
            self.headers[rel] = read_header(rel, h.read_text(encoding="utf-8"))
        for q in self.expose:
            for e in self.entities():
                if e.qualname == q:
                    e.internal = False
                    for c in e.walk():
                        if c is not e and c.access == "public" and not c.name.startswith("detail_"):
                            c.internal = False
        return self

    def entities(self):
        for root in self.headers.values():
            for e in root.walk():
                if e.kind != "file":
                    yield e

    def public(self):
        return [e for e in self.entities() if not hidden(e) and e.qualname not in self.hide
                and e.kind != "namespace"]

    # -- what goes where -------------------------------------------------------

    def own_page(self, e: Entity) -> bool:
        if e.kind not in ("class", "struct"):
            return False
        if e.parent is not None and e.parent.kind in ("class", "struct"):
            return False        # a nested type is read on its outer type's page
        if self.is_behavior(e) or e.qualname in self.expose:
            return True
        methods = [c for c in e.children if c.kind == "function" and not hidden(c)
                   and c.name not in HOOKS and c.name != e.name]
        return len(methods) >= OWN_PAGE_MIN_FUNCTIONS

    @staticmethod
    def is_behavior(e: Entity) -> bool:
        return e.kind in ("class", "struct") and e.parent is not None and \
            e.parent.qualname == "rmp::behavior" and any(
                c.kind == "function" and c.name in HOOKS for c in e.children)

    def page_url(self, e: Entity) -> str:
        if self.is_behavior(e):
            return f"reference/behaviors/{e.name}.html"
        if e.kind == "namespace":
            return f"reference/namespaces/{slug_q(e.qualname)}.html"
        return f"reference/classes/{slug_q(e.qualname)}.html"

    def namespace_of(self, e: Entity) -> str:
        p = e.parent
        while p is not None and p.kind != "namespace" and p.kind != "file":
            p = p.parent
        return p.qualname if p is not None and p.kind == "namespace" else ""

    # -- building --------------------------------------------------------------

    def build(self, blob_url) -> list[RefPage]:
        self.blob_url = blob_url
        public = self.public()
        # Namespaces, merged across headers, in the order headers come.
        namespaces: dict[str, list[Entity]] = {}
        for root in self.headers.values():
            for e in root.walk():
                if e.kind == "namespace" and not hidden(e) and e.name:
                    namespaces.setdefault(e.qualname, []).append(e)
        types = [e for e in public if self.own_page(e)]
        # Index first, so that every page can link to every other.
        for q, parts in namespaces.items():
            url = f"reference/namespaces/{slug_q(q)}.html"
            self.index[q] = url
        for t in types:
            url = self.page_url(t)
            self.index[t.qualname] = url
            for c in t.walk():
                if c is not t and not hidden(c):
                    self.index.setdefault(c.qualname, f"{url}#{self.member_anchor(t, c)}")
        for e in public:
            if e.qualname in self.index:
                continue
            owner = self.inline_owner(e)
            if owner is None:
                continue
            ns = self.namespace_of(owner)
            url = (self.index.get(owner.qualname) or f"reference/namespaces/{slug_q(ns)}.html")
            url = url.split("#", 1)[0]   # the owner's own entry may carry an anchor
            anchor = self.member_anchor(None, e) if owner is e else \
                f"{anchor_id(owner.name)}-{anchor_id(e.name)}"
            if owner is e and e.kind in ("class", "struct", "enum"):
                anchor = anchor_id(e.name)
            self.index.setdefault(e.qualname, f"{url}#{anchor}")
        macros = [e for e in public if e.kind == "macro"]
        for m in macros:
            self.index[m.qualname] = f"reference/macros.html#{m.name}"

        for q, parts in namespaces.items():
            self._used_ids = set()
            page = RefPage(f"reference/namespaces/{slug_q(q)}.html", q,
                           self.namespace_summary(q, parts), "namespace", parts,
                           nav_title=q, order=_ns_order(q), source=parts[0].header, line=parts[0].line)
            page.body = self.render_namespace(page, parts)
            self.pages.append(page)
        for t in types:
            self._used_ids = set()
            kind = "behavior" if self.is_behavior(t) else "class"
            title = self.expose.get(t.qualname, {}).get("title", t.qualname)
            page = RefPage(self.page_url(t), title,
                           prose.first_sentence(t.doc) or self.fallback_summary(t), kind, [t],
                           nav_title=t.name if kind == "behavior" else title.removeprefix("rmp::"),
                           source=t.header, line=t.line)
            page.body = self.render_type(page, t)
            self.pages.append(page)
        if macros:
            self._used_ids = set()
            page = RefPage("reference/macros.html", "Macros",
                           "The macros a game writes: the entry point, and the values the .toml sets.",
                           "macros", macros, nav_title="Macros", order=90,
                           source="include/rmp/app.h")
            page.body = self.render_macros(page, macros)
            self.pages.append(page)
        for folder, title, summary, order in (
                ("namespaces", "Namespaces", "Every namespace of the framework, and what is in it.", 10),
                ("classes", "Classes", "The framework's classes and structs that have pages of their own.", 20),
                ("behaviors", "Behaviors", "The catalogue of behaviors in rmp::behavior: what each one does to the object that has it.", 30)):
            members = [p for p in self.pages if p.url.startswith(f"reference/{folder}/")]
            page = RefPage(f"reference/{folder}/index.html", title, summary, "index", [],
                           nav_title=title, order=order)
            page.body = self.render_list(page, members)
            self.pages.append(page)
        return self.pages

    def inline_owner(self, e: Entity) -> Entity | None:
        """The entity whose page section shows `e`: itself for a top-level
        declaration of a namespace, its struct for a field of an inline struct."""
        p = e.parent
        if p is None or p.kind in ("namespace", "file"):
            return e
        if p.kind in ("class", "struct", "enum"):
            if p.qualname in self.index and self.own_page(p):
                return p
            return p if self.inline_owner(p) is p else None
        return None

    def member_anchor(self, owner: Entity | None, c: Entity) -> str:
        if owner is not None and c.parent is not owner and c.parent is not None:
            # A member of a nested type on the page: Value::Ref::get -> Ref-get
            return f"{anchor_id(c.parent.name)}-{anchor_id(c.name)}"
        return anchor_id(c.name)

    def namespace_summary(self, q: str, parts: list[Entity]) -> str:
        own = self.config.get("namespaces", {}).get(q, {}).get("summary")
        if own:
            return own
        root = parts[0]
        while root.parent is not None:
            root = root.parent
        return prose.first_sentence(root.doc) or f"The namespace {q}."

    @staticmethod
    def fallback_summary(t: Entity) -> str:
        return f"{t.kind} {t.qualname}."

    # -- links inside comments ---------------------------------------------------

    def link(self, current_url: str):
        def resolve(code: str):
            name = code.strip()
            name = re.sub(r"\(.*\)$", "", name)
            name = re.sub(r"<[^<>]*>$", "", name)
            candidates = [name]
            if not name.startswith("rmp::"):
                candidates.append("rmp::" + name)
            for cand in candidates:
                target = self.index.get(cand)
                if target is None:
                    continue
                if target.startswith(current_url + "#"):
                    return target[len(current_url):]
                if target == current_url:
                    return None
                return "/" + target
            return None
        return resolve

    # -- rendering ------------------------------------------------------------------

    def meta(self, e: Entity, kind: str, include: bool = False) -> str:
        parts = [f'<span class="badge">{html.escape(kind)}</span>']
        if include:
            parts.append(f"<code>#include &lt;{html.escape(e.header.removeprefix('include/'))}&gt;</code>")
        url = self.blob_url(e.header, e.line, e.end_line or e.line)
        parts.append(f'<a href="{html.escape(url)}">{html.escape(e.header)}:{e.line}</a>')
        return f'<div class="entity-meta">{" ".join(parts)}</div>'

    def signature(self, e: Entity) -> str:
        sig = e.signature
        if e.kind in ("field", "constant") and e.value:
            sig = f"{sig}{e.value}" if e.value.startswith("{") else f"{sig} = {e.value}"
        if e.template:
            sig = e.template + "\n" + sig
        return sig

    def render_type(self, page: RefPage, t: Entity) -> str:
        link = self.link(page.url)
        out = [f"<h1><code>{html.escape(page.title)}</code></h1>",
               self.meta(t, "behavior" if page.kind == "behavior" else t.kind, include=True)]
        if t.signature and page.title == t.qualname:
            out.append(f'<div class="signature">{highlight(self.signature(t), "cpp")}</div>')
        if t.doc:
            out.append(prose.to_html(t.doc, link))
        if page.kind == "behavior":
            out.append(self.behavior_usage(t))
        out += self.render_members(page, t, link)
        return "\n".join(x for x in out if x)

    def behavior_usage(self, t: Entity) -> str:
        hooks = [c.name for c in t.children if c.kind == "function" and c.name in HOOKS and not hidden(c)]
        lines = [f"<p>Added to an object with <code>add&lt;rmp::behavior::{html.escape(t.name)}&gt;()</code>"]
        if hooks:
            names = ", ".join(f"<code>{h}</code>" for h in hooks)
            lines.append(f"; the framework calls its {names} with the object it is on.</p>")
        else:
            lines.append(".</p>")
        return "".join(lines)

    def render_members(self, page: RefPage, t: Entity, link, heading="h2") -> list[str]:
        out = []
        members = [c for c in t.children if not hidden(c) and c.qualname not in self.hide
                   and not (page.kind == "behavior" and c.kind == "function" and c.name in HOOKS)]
        fields = [c for c in members if c.kind in ("field", "constant") and not c.static]
        others = [c for c in members if c not in fields]
        if fields and page.kind == "behavior":
            out.append('<h2 id="fields">Fields</h2>')
            out.append(self.field_table(t, fields, link, prefix=""))
            members = others
        groups: list[tuple[str, str, list[Entity]]] = []
        for m in members:
            if m.kind in ("class", "struct") and self.own_page(m):
                continue
            if not groups or groups[-1][0] != m.group:
                groups.append((m.group, m.group_doc, []))
            groups[-1][2].append(m)
        nested = []
        for title, intro, items in groups:
            if title:
                gid = "group-" + re.sub(r"[^\w]+", "-", title.lower()).strip("-")[:48]
                out.append(f'<h2 id="{gid}">{prose.inline(title, link)}</h2>')
                rest = intro.split("\n", 1)[1] if "\n" in intro else ""
                if rest.strip():
                    out.append(prose.to_html(rest.strip("\n"), link))
            for block in self.runs(items):
                first = block[0]
                if first.kind in ("class", "struct") and t.kind in ("class", "struct") and \
                        any(c.kind == "function" and not hidden(c) for c in first.children):
                    nested.append(first)   # a nested class with methods: a section of its own
                    continue
                out.append(self.render_block(page, block, link, owner=t))
        for n in nested:
            nid = self.unique(anchor_id(n.name))
            out.append(f'<h2 id="{nid}"><code>{html.escape(t.name)}::{html.escape(n.name)}</code></h2>')
            out.append(self.meta(n, n.kind))
            if n.doc:
                out.append(prose.to_html(n.doc, link))
            inner = self.render_members(page, n, link)
            out += [x.replace('<h2 id="group-', '<h3 id="group-').replace("</h2>", "</h3>")
                    if x.startswith('<h2 id="group-') else x for x in inner]
        return out

    def unique(self, wanted: str) -> str:
        """An id not yet used on the page being rendered: the second block of
        overloads of a name gets name-2."""
        used = self._used_ids
        hid, n = wanted, 1
        while hid in used:
            n += 1
            hid = f"{wanted}-{n}"
        used.add(hid)
        return hid

    def runs(self, items: list[Entity]) -> list[list[Entity]]:
        blocks: list[list[Entity]] = []
        for m in items:
            same_name = blocks and m.name == blocks[-1][-1].name and m.kind == blocks[-1][-1].kind
            shares_doc = blocks and m.run_doc and not m.doc and m.kind == blocks[-1][-1].kind \
                and m.kind not in ("class", "struct", "enum")
            if same_name or shares_doc:
                blocks[-1].append(m)
            else:
                blocks.append([m])
        return blocks

    def render_block(self, page: RefPage, block: list[Entity], link, owner: Entity | None) -> str:
        first = block[0]
        if first.kind in ("class", "struct") and len(block) == 1:
            return self.render_inline_struct(page, first, link)
        if first.kind == "enum" and len(block) == 1:
            return self.render_enum(page, first, link)
        names: list[str] = []
        for m in block:
            if m.name not in names:
                names.append(m.name)
        prefix = ""
        par = first.parent
        if par is not None and par.kind in ("class", "struct") and par.parent is not None \
                and par.parent.kind in ("class", "struct"):
            prefix = f"{anchor_id(par.name)}-"   # Value::Ref::get on Value's page: #Ref-get
        ids = [self.unique(prefix + anchor_id(n)) for n in names]
        title = ", ".join(f"<code>{html.escape(n)}</code>" for n in names)
        out = [f'<section class="entity" id="{ids[0]}">']
        for extra in ids[1:]:
            out.append(f'<span id="{extra}"></span>')
        out.append(f"<h3>{title}</h3>")
        for m in block:
            out.append(f'<div class="signature">{highlight(self.signature(m), "cpp")}</div>')
        out.append(self.meta(first, _kind_label(first)))
        if first.doc:
            out.append(prose.to_html(first.doc, link))
        elif first.run_doc and len(block) == 1:
            out.append(prose.to_html(first.run_doc, link))
        for m in block:
            if m.trailing:
                lead = f"<code>{html.escape(m.name)}</code>: " if len(block) > 1 else ""
                out.append(f"<p>{lead}{prose.inline(_sentence(m.trailing), link)}</p>")
        out.append("</section>")
        return "\n".join(out)

    def field_table(self, t: Entity, fields: list[Entity], link, prefix: str) -> str:
        rows = []
        for f in fields:
            fid = f"{prefix}{anchor_id(f.name)}"
            words = f.signature.rsplit(" ", 1)
            ftype = words[0] if len(words) == 2 else ""
            default = f.value or ""
            text = f.doc or f.trailing or f.run_doc or ""
            rows.append(
                f'<tr id="{fid}"><td><code>{html.escape(f.name)}</code></td>'
                f'<td class="type"><code>{html.escape(ftype)}</code></td>'
                f"<td>{('<code>' + html.escape(default) + '</code>') if default else ''}</td>"
                f"<td>{prose.to_html(_sentence(text), link) if text else ''}</td></tr>")
        return ('<table class="fields"><thead><tr><th>Field</th><th>Type</th><th>Default</th>'
                f'<th>What it is</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')

    def render_inline_struct(self, page: RefPage, s: Entity, link) -> str:
        sid = anchor_id(s.name)
        out = [f'<section class="entity" id="{sid}">', f"<h3><code>{html.escape(s.name)}</code></h3>",
               f'<div class="signature">{highlight(self.signature(s), "cpp")}</div>',
               self.meta(s, s.kind)]
        if s.doc:
            out.append(prose.to_html(s.doc, link))
        children = [c for c in s.children if not hidden(c) and c.qualname not in self.hide]
        fields = [c for c in children if c.kind in ("field", "constant")]
        if fields:
            out.append(self.field_table(s, fields, link, prefix=f"{sid}-"))
        for c in children:
            if c.kind == "function":
                out.append(f'<div class="signature" id="{sid}-{anchor_id(c.name)}">'
                           f'{highlight(self.signature(c), "cpp")}</div>')
                text = c.doc or c.trailing or c.run_doc
                if text:
                    out.append(prose.to_html(_sentence(text) if not c.doc else text, link))
        out.append("</section>")
        return "\n".join(out)

    def render_enum(self, page: RefPage, en: Entity, link) -> str:
        eid = anchor_id(en.name)
        out = [f'<section class="entity" id="{eid}">', f"<h3><code>{html.escape(en.name)}</code></h3>",
               f'<div class="signature">{highlight(en.signature, "cpp")}</div>',
               self.meta(en, "enum")]
        if en.doc:
            out.append(prose.to_html(en.doc, link))
        rows = []
        for m in en.children:
            text = m.doc or m.trailing
            rows.append(f'<tr id="{eid}-{anchor_id(m.name)}"><td><code>{html.escape(m.name)}</code></td>'
                        f"<td>{('<code>' + html.escape(m.value) + '</code>') if m.value else ''}</td>"
                        f"<td>{prose.inline(_sentence(text), link) if text else ''}</td></tr>")
        out.append('<table class="fields"><thead><tr><th>Value</th><th></th><th>Means</th></tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table>')
        out.append("</section>")
        return "\n".join(out)

    def render_namespace(self, page: RefPage, parts: list[Entity]) -> str:
        link = self.link(page.url)
        q = page.title
        headers = []
        for p in parts:
            if p.header not in headers:
                headers.append(p.header)
        out = [f"<h1><code>{html.escape(q)}</code></h1>"]
        incs = " ".join(f"<code>#include &lt;{html.escape(h.removeprefix('include/'))}&gt;</code>"
                        for h in headers)
        out.append(f'<div class="entity-meta"><span class="badge">namespace</span> {incs}</div>')
        single = len(headers) == 1
        if single:
            root = self.headers[headers[0]]
            if root.doc:
                out.append(prose.to_html(root.doc, link))
        children = [c for p in parts for c in p.children]
        types = [c for c in children if c.kind in ("class", "struct") and self.own_page(c) and not hidden(c)]
        nested = [c for c in children if c.kind == "namespace" and not hidden(c) and c.name]
        if types or nested:
            out.append('<h2 id="pages">On pages of their own</h2><ul>')
            for t in types:
                out.append(f'<li><a href="/{self.index[t.qualname]}"><code>{html.escape(t.qualname)}</code></a>'
                           f" — {prose.inline(prose.first_sentence(t.doc) or t.kind)}</li>")
            for n in nested:
                out.append(f'<li><a href="/{self.index[n.qualname]}"><code>{html.escape(n.qualname)}</code></a>'
                           f" — {html.escape(self.namespace_summary(n.qualname, [n]))}</li>")
            out.append("</ul>")
        for p in parts:
            items = [c for c in p.children if not hidden(c) and c.qualname not in self.hide
                     and c.kind not in ("namespace", "macro")
                     and not (c.kind in ("class", "struct") and self.own_page(c))]
            if not items:
                continue
            if not single:
                root = self.headers[p.header]
                hid = "header-" + re.sub(r"[^\w]+", "-", p.header.removeprefix("include/rmp/"))
                out.append(f'<h2 id="{hid}">From <code>{html.escape(p.header.removeprefix("include/"))}</code></h2>')
                summary = prose.first_sentence(root.doc)
                if summary:
                    out.append(f"<p>{prose.inline(summary, link)}</p>")
            fake = Entity("namespace", p.name, p.qualname, p.header, p.line)
            fake.children = items
            out += self.render_members(page, fake, link)
        return "\n".join(x for x in out if x)

    def render_macros(self, page: RefPage, macros: list[Entity]) -> str:
        link = self.link(page.url)
        out = ["<h1>Macros</h1>",
               "<p>The framework's macros are all spelled <code>RMP_</code>: the preprocessor has one "
               "namespace, shared with raylib, the C library and the game.</p>"]
        for m in macros:
            out.append(f'<section class="entity" id="{m.name}"><h3><code>{html.escape(m.name)}</code></h3>')
            out.append(f'<div class="signature">{highlight(m.signature, "cpp")}</div>')
            out.append(self.meta(m, "macro"))
            if m.doc:
                out.append(prose.to_html(m.doc, link))
            if len(m.branches) > 1:
                rows = "".join(f"<tr><td><code>{html.escape(c or '#else')}</code></td>"
                               f"<td><code>{html.escape(_one_line(b))}</code></td></tr>"
                               for c, b in m.branches)
                out.append('<p>Defined per platform:</p><table class="fields"><thead><tr><th>When</th>'
                           f"<th>Expands to</th></tr></thead><tbody>{rows}</tbody></table>")
            out.append("</section>")
        return "\n".join(out)

    def render_list(self, page: RefPage, members: list[RefPage]) -> str:
        rows = "".join(f'<tr><td><a href="/{p.url}"><code>{html.escape(p.title)}</code></a></td>'
                       f"<td>{prose.inline(p.description)}</td></tr>"
                       for p in sorted(members, key=lambda p: (p.order, p.title)))
        return (f"<h1>{html.escape(page.title)}</h1><p>{html.escape(page.description)}</p>"
                f'<table><thead><tr><th>Name</th><th>What it is</th></tr></thead><tbody>{rows}</tbody></table>')

    # -- coverage ---------------------------------------------------------------------

    def undocumented(self) -> list[Entity]:
        """Every public declaration nothing describes."""
        out = []
        for e in self.public():
            if e.covered:
                continue
            if e.kind == "function" and e.name in HOOKS and e.parent is not None \
                    and e.parent.qualname not in ("rmp::Scene", "rmp::Object"):
                continue    # a hook: what it means is documented once, on Scene and Object
            if e.kind == "member" and e.parent is not None and e.parent.doc:
                continue    # an enum's values are read in its documented table
            if e.qualname in self.config.get("allow_undocumented", {}):
                continue
            out.append(e)
        return out


def _ns_order(q: str) -> float:
    return {"rmp": 0}.get(q, 10 + q.count("::"))


def _kind_label(e: Entity) -> str:
    if e.kind == "function":
        if e.name in HOOKS:
            return "hook"
        return "static function" if e.static else "function"
    return e.kind


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _one_line(s: str) -> str:
    s = re.sub(r"\s*\\\s*\n\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) < 120 else s[:117] + "..."
