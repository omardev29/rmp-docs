"""The build: fragments and headers in, a static site out.

    content/**/*.html    a page each: an HTML fragment (its <article> only)
                         after a front-matter comment
    templates/layout.html  what goes around every page
    the framework at FRAMEWORK_REF   the headers (the reference), the examples
                         (included code), the counts and lists pages quote

Every transform here is something a page author would otherwise do by hand,
and could then do wrong: highlighting, quoting a file, linking a name,
numbering headings into a table of contents, making a link relative.
"""

from __future__ import annotations

import hashlib
import html
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import dom, prose
from .checks import Problem
from .highlight import LANGS, highlight
from .facts import Facts
from . import generated
from . import examples as examples_mod
from .reference import Reference
from .snippets import Snippet, harness_file
from .project import ProjectFile
from . import search as search_index

DOCS = Path(__file__).resolve().parents[2]

CSS_ORDER = ("tokens.css", "base.css", "layout.css", "components.css")
SKIP_TEXT = {"pre", "code", "script", "style", "kbd", "samp", "svg", "title"}
EXT_LANG = {".cpp": "cpp", ".hpp": "cpp", ".h": "cpp", ".c": "c", ".toml": "toml",
            ".sh": "shell", ".ps1": "powershell", ".cmake": "cmake", ".txt": "cmake",
            ".json": "json", ".yml": "yaml", ".yaml": "yaml"}


@dataclass
class Page:
    url: str
    title: str
    description: str
    source: str
    section: str
    order: float = 100
    nav_title: str = ""
    kind: str = "content"
    root: dom.Node | None = None
    body: str = ""
    toc: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    first_line: int = 1

    @property
    def depth(self) -> int:
        return self.url.count("/")

    @property
    def root_prefix(self) -> str:
        return "../" * self.depth


def relative(from_url: str, to: str) -> str:
    """A link from one page to a site path ("manual/x.html#y"), relative, so
    the site works under any prefix and from the file system."""
    path, _, frag = to.partition("#")
    if not path:
        return "#" + frag
    base = posixpath.dirname(from_url)
    rel = posixpath.relpath(path, base or ".")
    return rel + ("#" + frag if frag else "")


def slug(text: str) -> str:
    s = re.sub(r"[`'\"]", "", text.lower())
    s = re.sub(r"[^\w]+", "-", s).strip("-")
    return s or "section"


FRONT = re.compile(r"\A\s*<!--(.*?)-->\s*", re.S)


def front_matter(text: str) -> tuple[dict, str, int]:
    m = FRONT.match(text)
    if not m:
        return {}, text, 1
    meta = {}
    for line in m.group(1).strip().splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"front matter line without a colon: {line!r}")
        meta[key.strip()] = value.strip()
    consumed = text[:m.end()]
    return meta, text[m.end():], consumed.count("\n") + 1


class Site:
    def __init__(self, framework: Path | None = None, out: Path | None = None,
                 docs: Path = DOCS, examples_web: Path | None = None, posters: Path | None = None):
        self.docs = docs
        self.config = tomllib.loads((docs / "site.toml").read_text(encoding="utf-8"))
        self.refconf = tomllib.loads((docs / "reference.toml").read_text(encoding="utf-8"))
        self.ref = (docs / "FRAMEWORK_REF").read_text(encoding="utf-8").strip()
        self.framework = self._framework(framework)
        self.out = out or docs / "_site"
        self.pages: list[Page] = []
        self.problems: list[Problem] = []
        self.outputs: dict[str, str] = {}
        self.warnings: list[str] = []
        self.facts = Facts(self.framework)
        self.examples_web = examples_web
        self.posters_dir = posters
        self.examples: list = []
        self.examples_built: dict = {}
        self.posters: set = set()
        self.snippets: list[Snippet] = []
        self.project_files: dict[str, list[ProjectFile]] = {}   # project -> files, page order later

    # -- the framework ---------------------------------------------------------

    def _framework(self, given: Path | None) -> Path:
        candidates = [given, os.environ.get("RMP_FRAMEWORK"), self.docs.parent / "raylib_multiplatform"]
        for c in candidates:
            if c and (Path(c) / "include" / "rmp").is_dir():
                return Path(c).resolve()
        raise SystemExit("build.py: no framework checkout. Pass --framework PATH, set "
                         "RMP_FRAMEWORK, or put raylib_multiplatform next to rmp-docs.")

    def framework_head(self) -> str | None:
        got = subprocess.run(["git", "-C", str(self.framework), "rev-parse", "HEAD"],
                             capture_output=True, text=True)
        return got.stdout.strip() if got.returncode == 0 else None

    def framework_dirty(self) -> bool:
        got = subprocess.run(["git", "-C", str(self.framework), "status", "--porcelain",
                              "--", "include", "src", "examples", "tools", "CMakeLists.txt",
                              "CMakePresets.json", "raylib_multiplatform.toml"],
                             capture_output=True, text=True)
        return bool(got.stdout.strip())

    def blob_url(self, path: str, first: int = 0, last: int = 0) -> str:
        url = f"{self.config['site']['framework_repo']}/blob/{self.ref}/{path}"
        if first:
            url += f"#L{first}" + (f"-L{last}" if last and last != first else "")
        return url

    # -- reading the pages -----------------------------------------------------

    def discover(self):
        content = self.docs / "content"
        for path in sorted(content.rglob("*.html")):
            rel = path.relative_to(content).as_posix()
            text = path.read_text(encoding="utf-8")
            try:
                meta, body, first_line = front_matter(text)
            except ValueError as e:
                self.problems.append(Problem("front-matter", f"content/{rel}", 1, str(e)))
                continue
            section = rel.split("/", 1)[0] if "/" in rel else ""
            page = Page(url=rel, title=meta.get("title", ""), description=meta.get("description", ""),
                        source=f"content/{rel}", section=section,
                        order=float(meta.get("order", 100)), nav_title=meta.get("nav", ""),
                        meta=meta, first_line=first_line)
            root, errors = dom.parse(body, first_line)
            for e in errors:
                self.problems.append(Problem("html", page.source, e.line, e.message))
            page.root = root
            self.pages.append(page)

    def reference(self):
        self.reference_model = Reference(self.framework, self.refconf).read()
        refpages = self.reference_model.build(self.blob_url)
        for rp in refpages:
            if rp.url == "reference/macros.html":
                rp.body += "\n" + generated.defines_table(self.framework)
        for url, title, body in (generated.configuration_page(self.framework),
                                 generated.commands_page(self.framework)):
            root, errors = dom.parse(body)
            for e in errors:
                self.problems.append(Problem("html", f"generated:{url}", e.line, e.message))
            self.pages.append(Page(url=url, title=title, source="tools/rmpdocs/generated.py",
                                   description=f"Every {'key of the .toml' if 'config' in url else 'rmp command'}, "
                                               "read from the framework's own tool.",
                                   section="reference", kind="reference", order=80, nav_title=title,
                                   root=root))
        for rp in refpages:
            root, errors = dom.parse(rp.body)
            for e in errors:
                self.problems.append(Problem("html", f"generated:{rp.url}", e.line, e.message))
            self.pages.append(Page(url=rp.url, title=rp.title, description=rp.description,
                                   source=rp.source or "include/rmp", section="reference",
                                   kind="reference", order=rp.order,
                                   nav_title=rp.nav_title, root=root, meta={"line": rp.line}))

    def example_pages(self):
        conf_path = self.docs / "examples.toml"
        conf = tomllib.loads(conf_path.read_text(encoding="utf-8")) if conf_path.is_file() else {}
        self.examples, problems = examples_mod.load(self.framework, conf)
        for p in problems:
            self.problems.append(Problem("examples", "examples.toml", 0, p))
        # What can be shown: a web build for each playable example, a poster
        # for each. Copied into the site in write().
        for ex in self.examples:
            if self.examples_web is not None and ex.play:
                files = [self.examples_web / f"{ex.target}{e}" for e in (".js", ".wasm", ".data")]
                if files[0].is_file() and files[1].is_file():
                    self.examples_built[ex.target] = sum(f.stat().st_size for f in files if f.is_file())
            if self.posters_dir is not None and (self.posters_dir / f"{ex.target}.png").is_file():
                self.posters.add(examples_mod.poster_name(ex))
        repo = self.config["site"]["framework_repo"]
        areas = sorted({ex.area for ex in self.examples if ex.area})
        for area in areas:
            items = [ex for ex in self.examples if ex.area == area]
            rows = "".join(f'<li><a href="/{ex.url}">{html.escape(ex.title)}</a> — '
                           f"{examples_mod.markdown_inline(prose.first_sentence(ex.summary) or ex.summary, repo, self.ref)}</li>"
                           for ex in items)
            title = "UI" if area == "ui" else area.capitalize()
            body = f"<h1>{title}</h1><ul>{rows}</ul>"
            root, errors = dom.parse(body)
            self.pages.append(Page(url=f"examples/{area}/index.html", title=title,
                                   description=f"The examples under examples/{area}/.",
                                   source="tools/rmpdocs/examples.py", section="examples",
                                   kind="generated", order=areas.index(area) + 10, root=root))
        for i, ex in enumerate(self.examples):
            body = examples_mod.page_body(ex, repo, self.ref, self.examples_built, self.posters)
            root, errors = dom.parse(body)
            for e in errors:
                self.problems.append(Problem("html", f"generated:{ex.url}", e.line, e.message))
            summary = re.sub(r"<[^>]+>", "", examples_mod.markdown_inline(
                prose.first_sentence(ex.summary) or ex.title, repo, self.ref))
            self.pages.append(Page(url=ex.url, title=ex.title, description=html.unescape(summary),
                                   source=f"examples/{ex.path}", section="examples", kind="generated",
                                   order=i, root=root))

    # -- transforms ------------------------------------------------------------

    def transform(self, page: Page):
        root = page.root
        self._facts(page, root)
        self._generated_blocks(page, root)
        self._code_blocks(page, root)
        self._code_spans(page, root)
        self._headings(page, root)
        self._links(page, root)
        self._tables(root)
        page.body = dom.serialize(root)

    def _code_blocks(self, page: Page, root: dom.Node):
        for pre in [n for n in root.walk() if n.tag == "pre"]:
            if pre.parent is not None and pre.parent.tag == "div" and \
                    "code-block" in pre.parent.classes():
                continue     # generated already
            lang = pre.get("data-lang")
            include = pre.get("data-include")
            toml_out = ""   # what configure.py said about a .toml shown as refused
            caption = pre.get("data-file", "") if not pre.get("data-project") else ""
            link = ""
            if include:
                src = self.framework / include
                if not src.is_file():
                    self.problems.append(Problem("include", page.source, pre.line,
                                                 f"data-include names {include}, which the framework does not have"))
                    continue
                text = src.read_text(encoding="utf-8")
                region = pre.get("data-region")
                first = 1
                if region:
                    got = extract_region(text, region)
                    if got is None:
                        self.problems.append(Problem("include", page.source, pre.line,
                                                     f"{include} has no doc-region {region!r}"))
                        continue
                    text, first = got
                last = first + text.count("\n")
                lang = lang or EXT_LANG.get(Path(include).suffix, "text")
                caption = caption or include
                link = self.blob_url(include, first, last)
                code = text
            else:
                code = pre.text()
                if code.startswith("\n"):
                    code = code[1:]
                code = dedent(code.rstrip())
                project = pre.get("data-project")
                if project and page.kind == "content":
                    # A file of a tutorial's game: built with the whole project
                    # by --tier project, not by a harness.
                    if not pre.get("data-file"):
                        self.problems.append(Problem("snippets", page.source, pre.line,
                                                     "data-project needs data-file: which file this is"))
                    else:
                        caption = caption or pre.get("data-file")
                        self.project_files.setdefault(project, []).append(
                            ProjectFile(page.source, pre.line, pre.get("data-file"), code, lang,
                                        copy_from=pre.get("data-copy-from", "")))
                    if lang == "toml":
                        toml_out = self._toml(page, pre, code)
                elif lang in ("cpp", "c") and page.kind == "content":
                    self._snippet(page, pre, lang, code)
                elif lang == "toml" and page.kind == "content":
                    toml_out = self._toml(page, pre, code)
            if not lang:
                self.problems.append(Problem("code", page.source, pre.line,
                                             "a <pre> without data-lang; say what it is"))
                lang = "text"
            if lang not in LANGS:
                self.problems.append(Problem("code", page.source, pre.line,
                                             f"data-lang={lang!r} is not one of {', '.join(LANGS)}"))
                lang = "text"
            highlighted = highlight(code, lang)
            head = ""
            mistake = lang in ("cpp", "c") and pre.get("data-expect") == "error"
            if mistake:
                # A mistake shown on purpose looks like one, and says what the
                # compiler answers: the words the compile tier checks it prints.
                pre.attrs["class"] = " ".join([*pre.classes(), "expect-error"])
                caption = caption or "Does not compile"
                toml_out = ""
            if caption:
                inner = (f'<a class="file" href="{html.escape(link)}">{html.escape(caption)}</a>'
                         if link else f'<span class="file">{html.escape(caption)}</span>')
                head = f'<div class="code-head">{inner}<span class="spacer"></span></div>'
            extra = " ".join(c for c in pre.classes())
            attrs = {k: v for k, v in pre.attrs.items()
                     if k.startswith("data-") and k not in ("data-include", "data-region", "data-file")}
            attr_text = "".join(f' {k}="{html.escape(v)}"' for k, v in attrs.items())
            said = (f'<pre class="compiler-output" data-lang="text">{html.escape(toml_out, quote=False)}</pre>'
                    if toml_out else "")
            if mistake and pre.get("data-error"):
                said = ('<p class="compiler-output">The compiler refuses it, saying among other things: '
                        f'<code>{html.escape(pre.get("data-error"), quote=False)}</code></p>')
            markup = (f'<div class="code-block{(" " + extra) if extra else ""}"{attr_text}>{head}'
                      f'<pre data-lang="{lang}"><code>{highlighted}</code></pre>{said}</div>')
            replace(pre, dom.Raw(markup, pre.line))

    def _generated_blocks(self, page: Page, root: dom.Node):
        """<div data-generated="targets-table"></div>: a table the build makes
        from the framework's tools."""
        for n in [n for n in root.walk() if n.get("data-generated")]:
            if n.get("data-generated") == "examples-gallery":
                markup = examples_mod.gallery(self.examples, self.posters,
                                              self.config["site"]["framework_repo"], self.ref)
            else:
                make = generated.GENERATED_BLOCKS.get(n.get("data-generated"))
                if make is None:
                    self.problems.append(Problem("facts", page.source, n.line,
                                                 f"data-generated={n.get('data-generated')!r} is not a table the build knows"))
                    continue
                markup = make(self.framework)
            # Parsed, not pasted: its links are rewritten and checked like the page's own.
            made, errors = dom.parse(markup)
            for e in errors:
                self.problems.append(Problem("html", page.source, n.line, f"generated block: {e.message}"))
            wrapper = dom.Node("div", {"class": "generated"})
            for c in list(made.children):
                wrapper.append(c)
            replace(n, wrapper)

    def _facts(self, page: Page, root: dom.Node):
        """{{count:targets}} and friends: the framework's number, not a typed one."""
        for node in root.walk():
            for child in node.children:
                if isinstance(child, dom.Text) and "{{" in child.data:
                    def value(m, line=child.line):
                        try:
                            return self.facts.value(m.group(1), m.group(2))
                        except KeyError as e:
                            self.problems.append(Problem("facts", page.source, line, str(e).strip("'\"")))
                            return m.group(0)
                    child.data = re.sub(r"\{\{(count|list):([\w-]+)\}\}", value, child.data)

    def _snippet(self, page: Page, pre: dom.Node, lang: str, code: str):
        """Record a C or C++ block for the compile tier, or say why it cannot be."""
        harness = pre.get("data-harness")
        if not harness:
            self.problems.append(Problem(
                "snippets", page.source, pre.line,
                f"a {lang} block that nothing compiles: give it data-harness (one of "
                "file, toplevel, function, scene, object, members, c99) or quote it with "
                "data-include from a source the framework builds"))
            return
        if harness_file(harness) is None:
            self.problems.append(Problem("snippets", page.source, pre.line,
                                         f"data-harness={harness!r} is not a file in snippets/harness/"))
            return
        expect = pre.get("data-expect", "")
        if expect not in ("", "error"):
            self.problems.append(Problem("snippets", page.source, pre.line,
                                         f"data-expect={expect!r}: the only expectation is \"error\""))
        if expect == "error" and not pre.get("data-error"):
            self.problems.append(Problem("snippets", page.source, pre.line,
                                         "a block shown as a mistake says which error: data-error=\"...\""))
        self.snippets.append(Snippet(page.source, pre.line, lang, code, harness,
                                     given=pre.get("data-given", ""), expect_error=expect == "error",
                                     error_text=pre.get("data-error", "")))

    def _toml(self, page: Page, pre: dom.Node, code: str) -> str:
        """Every .toml block goes through the framework's own configure.py
        --check --config. One shown as refused (data-expect="reject") has to
        be refused, and what configure.py said is shown under it -- the real
        words, never typed. Returns that output, or ""."""
        if pre.get("data-config") == "no":
            if not pre.get("data-reason"):
                self.problems.append(Problem("toml", page.source, pre.line,
                                             "data-config=\"no\" needs a data-reason"))
            return ""
        expect = pre.get("data-expect", "")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "raylib_multiplatform.toml"
            cfg.write_text(code + "\n", encoding="utf-8")
            got = subprocess.run([sys.executable, "tools/configure.py", "--check", "--config", str(cfg)],
                                 capture_output=True, text=True, cwd=self.framework)
        said = (got.stdout + got.stderr).replace(str(cfg), "raylib_multiplatform.toml").strip()
        said = re.sub(r"^configure: (warning: thirdparty/raylib-ios is empty.*|\d+ warning\(s\) above)\n?",
                      "", said, flags=re.M).strip()
        if expect == "reject":
            if got.returncode == 0:
                self.problems.append(Problem("toml", page.source, pre.line,
                                             "shown as refused (data-expect=\"reject\"), and configure.py takes it"))
            return said
        if expect:
            self.problems.append(Problem("toml", page.source, pre.line,
                                         f"data-expect={expect!r}: the only expectation is \"reject\""))
        if got.returncode != 0:
            self.problems.append(Problem("toml", page.source, pre.line,
                                         f"configure.py refuses this .toml:\n{said[:500]}"))
        return ""

    def _code_spans(self, page: Page, root: dom.Node):
        for node in list(root.walk()):
            if node.tag in SKIP_TEXT:
                continue
            new_children = []
            changed = False
            for child in node.children:
                if isinstance(child, dom.Text) and "`" in child.data and not _inside(node, SKIP_TEXT):
                    parts = re.split(r"`([^`\n]+)`", child.data)
                    for i, part in enumerate(parts):
                        if i % 2:
                            code = dom.el("code", None, part)
                            new_children.append(code)
                        elif part:
                            new_children.append(dom.Text(part, child.line))
                    changed = True
                else:
                    new_children.append(child)
            if changed:
                node.children = []
                for c in new_children:
                    node.append(c)

    def _headings(self, page: Page, root: dom.Node):
        seen: dict[str, int] = {}
        for n in root.walk():
            if n.tag not in ("h2", "h3", "h4"):
                continue
            owner = n.parent
            if owner is not None and owner.tag == "section" and owner.get("id") \
                    and owner.children and next((c for c in owner.children
                                                 if isinstance(c, dom.Node)), None) is n:
                # A reference entry: the section carries the id, the heading names it.
                page.toc.append((int(n.tag[1]), owner.get("id"), n.text().strip()))
                continue
            hid = n.get("id") or slug(n.text())
            if hid in seen and not n.get("id"):
                seen[hid] += 1
                hid = f"{hid}-{seen[hid]}"
            seen.setdefault(hid, 1)
            n.attrs["id"] = hid
            if n.tag in ("h2", "h3"):
                page.toc.append((int(n.tag[1]), hid, n.text().strip()))
            if page.kind == "content":
                n.append(dom.el("a", {"class": "heading-anchor", "href": f"#{hid}",
                                      "aria-label": "Link to this section"}, "#"))

    def _links(self, page: Page, root: dom.Node):
        for n in root.walk():
            if n.tag != "a" or "href" not in n.attrs:
                continue
            href = n.attrs["href"]
            if href.startswith("ref:"):
                name = href[4:]
                target = self.reference_model.index.get(name)
                if target is None:
                    self.problems.append(Problem("names", page.source, n.line,
                                                 f"ref:{name} names nothing in the reference"))
                    continue
                n.attrs["href"] = relative(page.url, target)
            elif href.startswith("fw:"):
                path, _, frag = href[3:].partition("#")
                m = re.fullmatch(r"L(\d+)(?:-L(\d+))?", frag) if frag else None
                n.attrs["href"] = self.blob_url(path, int(m.group(1)) if m else 0,
                                                int(m.group(2) or 0) if m else 0)
                n.attrs["data-fw-path"] = href[3:]
            elif href.startswith("/"):
                n.attrs["href"] = relative(page.url, href[1:])

    def _tables(self, root: dom.Node):
        for t in [n for n in root.walk() if n.tag == "table"]:
            if t.parent is not None and "table-wrap" in t.parent.classes():
                continue
            wrap = dom.Node("div", {"class": "table-wrap"})
            replace(t, wrap)
            wrap.append(t)

    # -- the frame ---------------------------------------------------------------

    def sections(self) -> list[dict]:
        return self.config["sections"]

    def section_pages(self, section: str) -> list[Page]:
        pages = [p for p in self.pages if p.section == section]
        return sorted(pages, key=lambda p: (p.url.count("/") > 1 and p.url.rsplit("/", 1)[0] or "",
                                            0 if p.url.endswith("index.html") else 1,
                                            p.order, p.title))

    def nav_tree(self, current: Page) -> str:
        if not current.section:
            return ""
        pages = [p for p in self.pages if p.section == current.section]
        landing = next((p for p in pages if p.url == f"{current.section}/index.html"), None)
        # Groups: the folders under the section, each with an index.html.
        groups: dict[str, list[Page]] = {}
        loose: list[Page] = []
        for p in pages:
            parts = p.url.split("/")
            if len(parts) == 2:
                if p is not landing:
                    loose.append(p)
            else:
                groups.setdefault(parts[1], []).append(p)

        def link(p: Page, text: str | None = None) -> str:
            cur = ' aria-current="page"' if p is current else ""
            return (f'<a href="{html.escape(relative(current.url, p.url))}"{cur}>'
                    f"{html.escape(text or p.nav_title or p.title)}</a>")

        out = ['<ul class="nav-tree">']
        if landing:
            out.append(f"<li>{link(landing, landing.nav_title or 'Overview')}</li>")
        for p in sorted(loose, key=lambda p: (p.order, p.title)):
            out.append(f"<li>{link(p)}</li>")
        ordered = []
        for name, members in groups.items():
            index = next((m for m in members if m.url.endswith(f"{name}/index.html")), None)
            ordered.append((index.order if index else 100, name, index, members))
        for _order, name, index, members in sorted(ordered, key=lambda x: (x[0], x[1])):
            title = index.title if index else name
            label = (f'<a class="nav-group" href="{html.escape(relative(current.url, index.url))}">'
                     f"{html.escape(index.nav_title or title)}</a>" if index
                     else f'<span class="nav-group">{html.escape(title)}</span>')
            out.append(f"<li>{label}<ul>")
            for p in sorted([m for m in members if m is not index], key=lambda p: (p.order, p.title)):
                out.append(f"<li>{link(p)}</li>")
            out.append("</ul></li>")
        out.append("</ul>")
        return "\n".join(out)

    def flat_order(self, section: str) -> list[Page]:
        """The section's pages in the order the sidebar shows them."""
        tree = self.nav_tree_order(section)
        return tree

    def project_steps(self) -> dict:
        """project -> [Step], one per page that has files of it, in the order
        the sidebar shows the pages."""
        from .project import Step
        order = []
        for s in self.sections():
            order += self.nav_tree_order(s["id"])
        rank = {p.source: i for i, p in enumerate(order)}
        out = {}
        for name, files in self.project_files.items():
            steps: dict[str, Step] = {}
            for f in files:
                steps.setdefault(f.page, Step(f.page)).files.append(f)
            out[name] = sorted(steps.values(), key=lambda s: rank.get(s.page, 10**6))
        return out

    def nav_tree_order(self, section: str) -> list[Page]:
        pages = [p for p in self.pages if p.section == section]
        landing = [p for p in pages if p.url == f"{section}/index.html"]
        loose = sorted([p for p in pages if p.url.count("/") == 1 and p not in landing],
                       key=lambda p: (p.order, p.title))
        groups: dict[str, list[Page]] = {}
        for p in pages:
            if p.url.count("/") >= 2:
                groups.setdefault(p.url.split("/")[1], []).append(p)
        ordered = []
        for name, members in groups.items():
            index = next((m for m in members if m.url.endswith(f"{name}/index.html")), None)
            rest = sorted([m for m in members if m is not index], key=lambda p: (p.order, p.title))
            ordered.append(((index.order if index else 100, name), ([index] if index else []) + rest))
        out = landing + loose
        for _key, members in sorted(ordered, key=lambda x: x[0]):
            out += members
        return out

    def render(self, page: Page, layout: str) -> str:
        sections = []
        for s in self.sections():
            cur = ' aria-current="true"' if s["id"] == page.section else ""
            sections.append(f'<a href="{html.escape(relative(page.url, s["id"] + "/index.html"))}"{cur}>'
                            f"{html.escape(s['title'])}</a>")
        section_title = next((s["title"] for s in self.sections() if s["id"] == page.section), "")
        toc_items = toc_html(page.toc)
        toc = (f'<p class="toc-title">On this page</p>{toc_items}' if page.toc else "")
        toc_top = (f'<details class="toc-top"><summary>On this page</summary>{toc_items}</details>'
                   if page.toc else "")
        crumbs = ""
        if page.section and not page.url.endswith(f"{page.section}/index.html"):
            parts = [f'<a href="{html.escape(relative(page.url, page.section + "/index.html"))}">'
                     f"{html.escape(section_title)}</a>"]
            pieces = page.url.split("/")
            if len(pieces) > 2:
                gi = next((p for p in self.pages if p.url == f"{pieces[0]}/{pieces[1]}/index.html"), None)
                if gi and gi is not page:
                    parts.append(f'<a href="{html.escape(relative(page.url, gi.url))}">'
                                 f"{html.escape(gi.nav_title or gi.title)}</a>")
            crumbs = f'<p class="breadcrumbs">{" › ".join(parts)}</p>'
        pager = ""
        if page.section:
            order = self.nav_tree_order(page.section)
            if page in order:
                i = order.index(page)
                prev_p = order[i - 1] if i > 0 else None
                next_p = order[i + 1] if i + 1 < len(order) else None
                bits = []
                if prev_p:
                    bits.append(f'<a class="prev" href="{html.escape(relative(page.url, prev_p.url))}">'
                                f"<small>Previous</small>{html.escape(prev_p.nav_title or prev_p.title)}</a>")
                if next_p:
                    bits.append(f'<a class="next" href="{html.escape(relative(page.url, next_p.url))}">'
                                f"<small>Next</small>{html.escape(next_p.nav_title or next_p.title)}</a>")
                if bits:
                    pager = f'<nav class="pager" aria-label="Previous and next">{"".join(bits)}</nav>'
        site_title = self.config["site"]["title"]
        page_title = site_title if not page.section and page.url == "index.html" else \
            f"{page.title} · {site_title}"
        source = page.source if page.kind == "content" else "tools/rmpdocs/reference.py"
        values = {
            "page_title": html.escape(page_title),
            "description": html.escape(page.description),
            "root": page.root_prefix,
            "path": html.escape(page.url),
            "sections": "".join(sections),
            "section_title": html.escape(section_title or "Pages"),
            "nav": self.nav_tree(page),
            "breadcrumbs": crumbs,
            "toc": toc,
            "toc_top": toc_top,
            "content": page.body,
            "pager": pager,
            "framework_url": self.config["site"]["framework_repo"],
            "docs_url": self.config["site"]["docs_repo"],
            "ref": self.ref,
            "ref_short": self.ref[:8],
            "source": html.escape(source),
            "shell_class": " single" if not page.section else "",
        }
        out = re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], layout)
        return out

    # -- the whole thing ---------------------------------------------------------

    def build(self, write: bool = True) -> "Site":
        head = self.framework_head()
        if head and head != self.ref:
            self.warnings.append(f"documenting the framework's working tree at {head[:8]}, "
                                 f"not FRAMEWORK_REF {self.ref[:8]}")
        if self.framework_dirty():
            self.warnings.append("the framework's working tree has uncommitted changes")
        self.discover()
        self.reference()
        self.example_pages()
        for page in self.pages:
            self.transform(page)
        layout = (self.docs / "templates" / "layout.html").read_text(encoding="utf-8")
        for page in self.pages:
            self.outputs[page.url] = self.render(page, layout)
        summaries = {e.qualname: (e.kind, prose.first_sentence(e.doc or e.run_doc or e.trailing))
                     for e in self.reference_model.entities()}
        self.search_json = search_index.build(self.pages, self.reference_model.index, summaries)
        if write:
            self.write()
        return self

    def write(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        for url, text in self.outputs.items():
            path = self.out / url
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        assets = self.out / "assets"
        css = "\n".join((self.docs / "assets" / "css" / name).read_text(encoding="utf-8")
                        for name in CSS_ORDER)
        (assets).mkdir(parents=True, exist_ok=True)
        # The stylesheet lives at assets/site.css and the fonts under
        # assets/fonts/: its url("../fonts/...") paths were written from
        # assets/css/, one level deeper, so they are rewritten here.
        css = css.replace('url("../fonts/', 'url("fonts/')
        (assets / "site.css").write_text(css, encoding="utf-8")
        shutil.copytree(self.docs / "assets" / "js", assets / "js")
        shutil.copytree(self.docs / "assets" / "fonts", assets / "fonts")
        for extra in ("icon.svg",):
            src = self.docs / "assets" / extra
            if src.is_file():
                shutil.copy(src, assets / extra)
        (self.out / ".nojekyll").write_text("")
        (assets / "search.json").write_text(self.search_json, encoding="utf-8")
        play = (self.docs / "templates" / "play.html").read_text(encoding="utf-8")
        examples_mod.copy_artifacts(self.examples, self.examples_web, self.posters_dir, self.out, play)


def toc_html(entries: list[tuple[int, str, str]]) -> str:
    """Nested <ol> from (level, id, text), levels as the headings had them."""
    if not entries:
        return ""
    base = min(d for d, _, _ in entries)
    out: list[str] = []
    stack: list[int] = []
    for depth, hid, text in entries:
        depth = max(depth, base)
        item = f'<li><a href="#{html.escape(hid)}">{html.escape(text.strip())}</a>'
        if not stack:
            out.append("<ol>")
            stack.append(depth)
        elif depth > stack[-1]:
            out.append("<ol>")
            stack.append(depth)
        else:
            out.append("</li>")
            while len(stack) > 1 and depth < stack[-1]:
                out.append("</ol></li>")
                stack.pop()
        out.append(item)
    out.append("</li>")
    while len(stack) > 1:
        out.append("</ol></li>")
        stack.pop()
    out.append("</ol>")
    return "".join(out)


def dedent(text: str) -> str:
    lines = text.split("\n")
    widths = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip()]
    base = min(widths) if widths else 0
    return "\n".join(l[base:] for l in lines)


def extract_region(text: str, name: str) -> tuple[str, int] | None:
    """The lines between `// doc-region: name` and `// doc-region-end: name`,
    and the line number of the first of them."""
    lines = text.split("\n")
    start = end = None
    for i, line in enumerate(lines):
        s = line.strip()
        if re.fullmatch(rf"//\s*doc-region:\s*{re.escape(name)}", s):
            start = i + 1
        elif start is not None and re.fullmatch(rf"//\s*doc-region-end:\s*{re.escape(name)}", s):
            end = i
            break
    if start is None or end is None:
        return None
    return dedent("\n".join(lines[start:end]).rstrip()), start + 1


def replace(old, new):
    parent = old.parent
    i = parent.children.index(old)
    parent.children[i] = new
    new.parent = parent
    old.parent = None


def _inside(node, tags) -> bool:
    while node is not None:
        if getattr(node, "tag", None) in tags:
            return True
        node = node.parent
    return False


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
