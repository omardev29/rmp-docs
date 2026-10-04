"""The gates. Each one is a precise statement of a way the site could lie or
break, and a function that fails when it does.

Every gate here is registered with a name, and tests/test_gates_red.py
requires, for each name, a fixture under tests/fixtures/gates/<name>/bad/
that makes exactly that gate fail and one under good/ that it passes. A gate
nobody has seen fail is a hope with a name.

A gate reads a Context: the built pages (url -> html), the docs folder, the
configuration. The build makes one from the site; a test makes one from a
fixture folder, which is what lets a gate be proved red on four lines of HTML
instead of a whole site.
"""

from __future__ import annotations

import hashlib
import html
import re
import tomllib
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from . import dom

GATES: dict[str, tuple] = {}


@dataclass
class Problem:
    gate: str
    where: str
    line: int
    message: str

    def __str__(self):
        loc = f"{self.where}:{self.line}" if self.line else self.where
        return f"[{self.gate}] {loc}: {self.message}"


@dataclass
class Context:
    docs: Path
    outputs: dict = field(default_factory=dict)      # url -> html
    config: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)      # source path -> text (fragments)
    build_problems: list = field(default_factory=list)

    @classmethod
    def from_folder(cls, folder: Path) -> "Context":
        """A fixture: every .html under `out/` is a built page, `site.toml`
        the configuration, the rest of the folder is the docs tree."""
        config = {}
        if (folder / "site.toml").is_file():
            config = tomllib.loads((folder / "site.toml").read_text(encoding="utf-8"))
        outputs = {}
        out = folder / "out"
        if out.is_dir():
            for p in sorted(out.rglob("*.html")):
                outputs[p.relative_to(out).as_posix()] = p.read_text(encoding="utf-8")
        sources = {}
        content = folder / "content"
        if content.is_dir():
            for p in sorted(content.rglob("*.html")):
                sources["content/" + p.relative_to(content).as_posix()] = p.read_text(encoding="utf-8")
        return cls(docs=folder, outputs=outputs, config=config, sources=sources)


def gate(name: str, says: str):
    def register(fn):
        GATES[name] = (fn, says)
        return fn
    return register


def run(ctx: Context, only: list[str] | None = None) -> list[Problem]:
    problems = []
    for name, (fn, _says) in GATES.items():
        if only and name not in only:
            continue
        problems += fn(ctx)
    return problems


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def parsed(ctx: Context):
    for url, text in ctx.outputs.items():
        root, errors = dom.parse(text)
        yield url, root, errors


def ids_of(root) -> set[str]:
    return {n.attrs["id"] for n in root.walk() if "id" in n.attrs}


def _line(text: str, needle: str) -> int:
    i = text.find(needle)
    return text.count("\n", 0, i) + 1 if i >= 0 else 0


# ---------------------------------------------------------------------------
# the gates
# ---------------------------------------------------------------------------

@gate("html", "every page and every fragment is well-formed HTML: each element "
              "closed, closed in order, no attribute twice")
def check_html(ctx: Context) -> list[Problem]:
    out = [Problem("html", p.where, p.line, p.message) for p in ctx.build_problems
           if p.gate == "html"]
    for path, text in ctx.sources.items():
        body = re.sub(r"\A\s*<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        _root, errors = dom.parse(body)
        out += [Problem("html", path, e.line, e.message) for e in errors]
    for url, _root, errors in parsed(ctx):
        out += [Problem("html", url, e.line, e.message) for e in errors]
    return out


@gate("ids", "no id appears twice on a page: an anchor that means two places "
             "means the first one")
def check_ids(ctx: Context) -> list[Problem]:
    out = []
    for url, root, _ in parsed(ctx):
        seen = {}
        for n in root.walk():
            i = n.attrs.get("id")
            if i is None:
                continue
            if i in seen:
                out.append(Problem("ids", url, n.line,
                                   f'id="{i}" is used twice (first on line {seen[i]})'))
            seen.setdefault(i, n.line)
    return out


@gate("links", "every link inside the site reaches a page that exists, and the "
               "#anchor on it")
def check_links(ctx: Context) -> list[Problem]:
    out = []
    anchors = {url: ids_of(root) for url, root, _ in parsed(ctx)}
    files = set(anchors)
    assets = ctx.config.get("assets_present", None)
    for url, root, _ in parsed(ctx):
        for n in root.walk():
            for attr in ("href", "src"):
                target = n.attrs.get(attr)
                if target is None or re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("//"):
                    continue
                if n.tag == "link" or n.tag == "script" or (n.tag == "img"):
                    continue    # assets: the resources gate
                path, _, frag = target.partition("#")
                path = urllib.parse.unquote(path)
                if path:
                    base = url.rsplit("/", 1)[0] if "/" in url else ""
                    resolved = _normalise(f"{base}/{path}" if base else path)
                    if resolved.endswith("/"):
                        resolved += "index.html"
                else:
                    resolved = url
                if resolved not in files:
                    if assets is not None and resolved in assets:
                        continue
                    out.append(Problem("links", url, n.line, f"{target} leads to no page "
                                                             f"({resolved} does not exist)"))
                    continue
                if frag and urllib.parse.unquote(frag) not in anchors[resolved]:
                    out.append(Problem("links", url, n.line,
                                       f"{target}: {resolved} has no id {frag!r}"))
    return out


def _normalise(path: str) -> str:
    parts = []
    for p in path.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/".join(parts)


@gate("resources", "the site requests nothing from anywhere else: no CDN, no web "
                   "font service, no analytics -- every script, stylesheet, font, "
                   "image and frame is one of its own files")
def check_resources(ctx: Context) -> list[Problem]:
    out = []
    for url, root, _ in parsed(ctx):
        for n in root.walk():
            for attr in ("src", "href", "poster", "data"):
                if attr == "href" and n.tag not in ("link",):
                    continue
                v = n.attrs.get(attr)
                if v and re.match(r"([a-z][a-z0-9+.-]*:)?//", v, re.I):
                    out.append(Problem("resources", url, n.line,
                                       f"<{n.tag} {attr}={v!r}> loads from another site"))
            style = n.attrs.get("style", "")
            if re.search(r"url\(\s*['\"]?(https?:)?//", style):
                out.append(Problem("resources", url, n.line, "a style loads from another site"))
            if n.tag == "style" and re.search(r"(@import|url\()\s*['\"]?(https?:)?//", n.text()):
                out.append(Problem("resources", url, n.line, "a <style> loads from another site"))
    css = ctx.docs / "assets" / "css"
    if css.is_dir():
        for p in sorted(css.glob("*.css")):
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"(@import|url\()\s*['\"]?((https?:)?//[^'\")]+)", text):
                out.append(Problem("resources", f"assets/css/{p.name}", _line(text, m.group(0)),
                                   f"loads {m.group(2)} from another site"))
    js = ctx.docs / "assets" / "js"
    if js.is_dir():
        for p in sorted(js.glob("*.js")):
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"(fetch\(|\.src\s*=|import\s*\()\s*['\"](https?:)?//", text):
                out.append(Problem("resources", f"assets/js/{p.name}", _line(text, m.group(0)),
                                   "loads from another site"))
    return out


@gate("external-links", "a link that leaves the site goes to a host the site "
                        "allows (site.toml [links] allow), over https")
def check_external_links(ctx: Context) -> list[Problem]:
    allow = ctx.config.get("links", {}).get("allow", [])
    out = []
    for url, root, _ in parsed(ctx):
        for n in root.walk():
            if n.tag != "a":
                continue
            href = n.attrs.get("href", "")
            if not re.match(r"[a-z][a-z0-9+.-]*:", href):
                continue
            if href.startswith("mailto:"):
                continue
            if not href.startswith("https://"):
                out.append(Problem("external-links", url, n.line, f"{href}: not https"))
                continue
            if not any(href.startswith(a) for a in allow):
                out.append(Problem("external-links", url, n.line,
                                   f"{href}: not under any prefix in site.toml [links] allow"))
    return out


@gate("front-matter", "every page says what it is: a title and a one-sentence "
                      "description, for the tab, search and the link preview")
def check_front_matter(ctx: Context) -> list[Problem]:
    out = []
    for path, text in ctx.sources.items():
        m = re.match(r"\A\s*<!--(.*?)-->", text, re.S)
        meta = {}
        if m:
            for line in m.group(1).strip().splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        for key in ("title", "description"):
            if not meta.get(key):
                out.append(Problem("front-matter", path, 1, f"no {key} in the front matter"))
        d = meta.get("description", "")
        if d and not d.endswith("."):
            out.append(Problem("front-matter", path, 1, "the description is a sentence: end it with a full stop"))
    return out


@gate("forbidden", "no phrase site.toml [forbidden] lists appears on a page "
                   "(\"this template\", the retired `just` commands)")
def check_forbidden(ctx: Context) -> list[Problem]:
    phrases = ctx.config.get("forbidden", {}).get("phrases", [])
    out = []
    for url, root, _ in parsed(ctx):
        text = html.unescape(re.sub(r"<[^>]+>", " ", ctx.outputs[url]))
        for phrase in phrases:
            for m in re.finditer(re.escape(phrase), text, re.I):
                out.append(Problem("forbidden", url, 0, f"says {phrase!r}: "
                                   f"...{text[max(0, m.start() - 30):m.end() + 30].strip()}..."))
    return out


@gate("budgets", "no page, stylesheet or script grows past its budget in "
                 "site.toml [budgets]")
def check_budgets(ctx: Context) -> list[Problem]:
    b = ctx.config.get("budgets", {})
    out = []
    page_kb = b.get("page_kb")
    if page_kb:
        for url, text in ctx.outputs.items():
            size = len(text.encode("utf-8")) / 1024
            if size > page_kb:
                out.append(Problem("budgets", url, 0, f"{size:.0f} KB, over the {page_kb} KB page budget"))
    search_kb = b.get("search_kb")
    search = ctx.config.get("_search_json")
    if search_kb and search is not None and len(search.encode("utf-8")) / 1024 > search_kb:
        out.append(Problem("budgets", "assets/search.json", 0,
                           f"{len(search.encode('utf-8')) / 1024:.0f} KB, over the {search_kb} KB search budget"))
    for kind, folder, key in (("css", "css", "css_kb"), ("js", "js", "js_kb")):
        limit = b.get(key)
        d = ctx.docs / "assets" / folder
        if limit and d.is_dir():
            total = sum(p.stat().st_size for p in d.glob(f"*.{kind}")) / 1024
            if total > limit:
                out.append(Problem("budgets", f"assets/{folder}", 0,
                                   f"{total:.0f} KB of {kind}, over the {limit} KB budget"))
    return out


@gate("fonts", "every font the site serves is listed in assets/fonts/SOURCES.toml "
               "with where it came from and its sha256, and still matches it; each "
               "family carries its OFL.txt")
def check_fonts(ctx: Context) -> list[Problem]:
    folder = ctx.docs / "assets" / "fonts"
    out = []
    sources_path = folder / "SOURCES.toml"
    if not sources_path.is_file():
        return [Problem("fonts", "assets/fonts/SOURCES.toml", 0, "missing")]
    sources = tomllib.loads(sources_path.read_text(encoding="utf-8"))
    listed = {}
    for family, spec in sources.items():
        for f in spec.get("files", []):
            listed[f"{family}/{f['name']}"] = f
        if not (folder / family / "OFL.txt").is_file():
            out.append(Problem("fonts", f"assets/fonts/{family}", 0, "no OFL.txt beside the font"))
        for key in ("version", "url", "licence"):
            if not spec.get(key):
                out.append(Problem("fonts", "assets/fonts/SOURCES.toml", 0, f"{family}: no {key}"))
    for p in sorted(folder.rglob("*.woff2")):
        rel = p.relative_to(folder).as_posix()
        spec = listed.get(rel)
        if spec is None:
            out.append(Problem("fonts", f"assets/fonts/{rel}", 0, "not listed in SOURCES.toml"))
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != spec.get("sha256"):
            out.append(Problem("fonts", f"assets/fonts/{rel}", 0,
                               f"sha256 {got} is not the {spec.get('sha256')} SOURCES.toml pins"))
    for rel in listed:
        if not (folder / rel).is_file():
            out.append(Problem("fonts", f"assets/fonts/{rel}", 0, "listed in SOURCES.toml, not on disk"))
    return out


# --- colour -----------------------------------------------------------------

HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")


@gate("css-colours", "no stylesheet but tokens.css writes a colour: everything "
                     "else names a token, so the contrast gate sees every colour")
def check_css_colours(ctx: Context) -> list[Problem]:
    out = []
    folder = ctx.docs / "assets" / "css"
    if not folder.is_dir():
        return out
    for p in sorted(folder.glob("*.css")):
        if p.name == "tokens.css":
            continue
        text = p.read_text(encoding="utf-8")
        body = re.sub(r"@media\s*\(forced-colors[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", text)
        body = re.sub(r"@media\s+print[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", body)
        for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|\brgba?\((?!\s*0\s+0\s+0\s*/)|\bhsla?\(", body):
            out.append(Problem("css-colours", f"assets/css/{p.name}", _line(text, m.group(0)),
                               f"{m.group(0)}: name a token from tokens.css instead"))
    return out


def tokens(text: str) -> dict[str, dict[str, str]]:
    """{'light': {...}, 'dark': {...}}: the custom properties of the :root
    block and of the :root[data-theme="dark"] block."""
    themes = {}
    light = re.search(r"(?s)^:root\s*\{(.*?)^\}", text, re.M)
    dark = re.search(r'(?s)^:root\[data-theme="dark"\]\s*\{(.*?)^\}', text, re.M)
    for name, block in (("light", light), ("dark", dark)):
        if block:
            themes[name] = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block.group(1)))
    if "dark" in themes and "light" in themes:
        merged = dict(themes["light"])
        merged.update(themes["dark"])
        themes["dark"] = merged
    return themes


def _lum(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Body text 7:1 (WCAG AAA), everything else that is text 4.5:1 (AA).
CONTRAST_PAIRS = [
    ("--text", "--bg", 7.0), ("--text", "--bg-raised", 7.0), ("--text", "--bg-sunken", 7.0),
    ("--text-muted", "--bg", 4.5), ("--text-muted", "--bg-sunken", 4.5),
    ("--accent", "--bg", 4.5), ("--accent", "--bg-sunken", 4.5),
    ("--accent-text", "--accent", 4.5),
    ("--text", "--note", 7.0), ("--text", "--warn", 7.0), ("--text", "--danger", 7.0),
    ("--text", "--mark", 7.0),
] + [(f"--code-{k}", "--bg-sunken", 4.5) for k in "ktfsncpmav"] + [("--code-text", "--bg-sunken", 7.0)]


@gate("contrast", "every text colour against every background it is drawn on, in "
                  "both themes: 7:1 for body text, 4.5:1 for the rest (WCAG)")
def check_contrast(ctx: Context) -> list[Problem]:
    path = ctx.docs / "assets" / "css" / "tokens.css"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    themes = tokens(text)
    out = []
    # The media-query copy of the dark theme must be the same as the explicit
    # one, or "auto" and "dark" are two different themes.
    media = re.search(r'(?s)@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{(.*?)\n  \}', text)
    if media:
        auto = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", media.group(1)))
        explicit = re.search(r'(?s)^:root\[data-theme="dark"\]\s*\{(.*?)^\}', text, re.M)
        exp = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", explicit.group(1))) if explicit else {}
        if auto != exp:
            diff = sorted(k for k in set(auto) | set(exp) if auto.get(k) != exp.get(k))
            out.append(Problem("contrast", "assets/css/tokens.css", 0,
                               f"the dark theme differs between auto and explicit: {', '.join(diff)}"))
    for theme, values in themes.items():
        for fg, bg, need in CONTRAST_PAIRS:
            a, b = values.get(fg, ""), values.get(bg, "")
            if not HEX.fullmatch(a.strip()) or not HEX.fullmatch(b.strip()):
                out.append(Problem("contrast", "assets/css/tokens.css", 0,
                                   f"{theme}: {fg} or {bg} is not a #hex colour"))
                continue
            got = contrast(a.strip(), b.strip())
            if got < need:
                out.append(Problem("contrast", "assets/css/tokens.css", _line(text, f"{fg}:"),
                                   f"{theme}: {fg} {a} on {bg} {b} is {got:.2f}:1, needs {need}:1"))
    return out
