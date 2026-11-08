"""What a reader takes away from the site, made with it on every build so it
never goes stale:

  ai/<page>.md          every page as Markdown, for an AI or a text editor
  llms.txt              the index of them, as llmstxt.org lays one out
  llms-full.txt         every page in reading order, one text
  rmp-docs-ai.zip       the same pages in folders, one per section, numbered in
                        reading order, with an INDEX.md that says what is where
  print.html            the whole manual in one page, for the browser to print
                        or save as a PDF (the API reference stays on the site)

The Markdown is written from each page's own DOM, after the build has filled
it: headings, paragraphs, lists, tables, code blocks with their language, and
every link made absolute, so a page read alone still leads where it said.
"""

from __future__ import annotations

import html
import io
import posixpath
import re
import zipfile

from . import dom

SKIP = {"script", "style", "nav", "button", "svg", "img", "picture", "video", "audio",
        "canvas", "iframe", "noscript", "template"}
BLOCK = {"p", "div", "section", "article", "figure", "figcaption", "header", "footer", "main",
         "details", "summary", "dl", "dt", "dd", "blockquote", "pre", "table", "ul", "ol", "li",
         "h1", "h2", "h3", "h4", "h5", "h6", "hr"}


def md_path(url: str) -> str:
    """ai/manual/modules/dialogue.md for manual/modules/dialogue.html."""
    return "ai/" + re.sub(r"\.html$", ".md", url)


def absolute(href: str, page_url: str, base: str) -> str:
    if re.match(r"[a-z][a-z0-9+.-]*:", href) or href.startswith("//"):
        return href
    path, _, frag = href.partition("#")
    if path.startswith("/"):
        resolved = path.lstrip("/")
    elif path:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(page_url), path))
        if path.endswith("/"):
            resolved += "/"   # a folder: normpath took its slash away
    else:
        resolved = page_url
    if resolved in (".", "./"):
        resolved = ""
    if resolved == "" or resolved.endswith("/"):
        resolved += "index.html"
    return base + resolved + ("#" + frag if frag else "")


class Markdown:
    def __init__(self, page_url: str, base: str):
        self.page_url = page_url
        self.base = base

    # -- inline ----------------------------------------------------------------

    def inline(self, node) -> str:
        if isinstance(node, dom.Text):
            return re.sub(r"\s+", " ", html.unescape(node.data))
        if not isinstance(node, dom.Node):
            return ""
        tag = node.tag
        if tag in SKIP:
            return ""
        inner = "".join(self.inline(c) for c in node.children)
        if tag == "code" or tag == "kbd" or tag == "samp":
            text = node.text()
            fence = "``" if "`" in text else "`"
            return f"{fence}{text}{fence}" if text.strip() else ""
        if tag in ("strong", "b"):
            return f"**{inner.strip()}**" if inner.strip() else ""
        if tag in ("em", "i"):
            return f"*{inner.strip()}*" if inner.strip() else ""
        if tag == "br":
            return "  \n"
        if tag == "a" and "heading-anchor" in (node.get("class") or ""):
            return ""   # the # beside a heading: the page's own link to it
        if tag == "a":
            href = node.get("href")
            if not href or not inner.strip():
                return inner
            return f"[{inner.strip()}]({absolute(href, self.page_url, self.base)})"
        return inner

    def text_of(self, node) -> str:
        return re.sub(r"[ \t]+", " ", "".join(self.inline(c) for c in node.children)).strip()

    # -- blocks ----------------------------------------------------------------

    def blocks(self, node, depth: int = 0) -> list[str]:
        """The Markdown blocks of a node's children."""
        out: list[str] = []
        run: list = []

        def flush():
            text = re.sub(r"[ \t]+", " ", "".join(self.inline(c) for c in run)).strip()
            if text:
                out.append(text)
            run.clear()

        for c in node.children:
            if isinstance(c, dom.Node) and (c.tag in BLOCK or c.tag in SKIP):
                flush()
                out.extend(self.block(c, depth))
            else:
                run.append(c)
        flush()
        return out

    def block(self, node, depth: int) -> list[str]:
        tag = node.tag
        if tag in SKIP:
            return []
        if re.fullmatch(r"h[1-6]", tag):
            return [f"{'#' * int(tag[1])} {self.text_of(node)}"]
        if tag == "pre":
            lang = node.get("data-lang", "") or ""
            code = html.unescape(node.text()).strip("\n")
            fence = "````" if "```" in code else "```"
            return [f"{fence}{lang}\n{code}\n{fence}"]
        if tag in ("ul", "ol"):
            return [self.list_block(node, tag == "ol", depth)]
        if tag == "table":
            return [self.table(node)]
        if tag == "blockquote":
            inner = "\n\n".join(self.blocks(node, depth))
            return ["\n".join("> " + line if line else ">" for line in inner.splitlines())]
        if tag == "hr":
            return ["---"]
        if tag == "summary":
            return [f"**{self.text_of(node)}**"]
        return self.blocks(node, depth)

    def list_block(self, node, ordered: bool, depth: int) -> str:
        lines = []
        n = 0
        for li in node.children:
            if not isinstance(li, dom.Node) or li.tag != "li":
                continue
            n += 1
            mark = f"{n}." if ordered else "-"
            parts = self.blocks(li, depth + 1)
            pad = " " * (len(mark) + 1)
            first, *rest = parts or [""]
            lines.append(f"{mark} {first}".rstrip())
            for p in rest:
                lines.extend((pad + line) if line else "" for line in p.splitlines())
        return "\n".join(lines)

    def table(self, node) -> str:
        rows = []
        for tr in node.walk():
            if isinstance(tr, dom.Node) and tr.tag == "tr":
                cells = [self.text_of(c).replace("|", "\\|").replace("\n", " ")
                         for c in tr.children if isinstance(c, dom.Node) and c.tag in ("th", "td")]
                if cells:
                    rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
        out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(out)


def page_markdown(page, base: str) -> str:
    """One page as Markdown: its title, where it lives, and its content."""
    body, _ = dom.parse(page.body or "")
    blocks = Markdown(page.url, base).blocks(body)
    head = [f"# {page.title}"]
    if page.description:
        head.append(f"> {page.description}")
    head.append(f"Source: {base}{page.url}")
    # The page's own <h1> is its title, said once.
    if blocks and blocks[0].startswith("# "):
        blocks = blocks[1:]
    return "\n\n".join(head + blocks).strip() + "\n"


def reading_order(site) -> list:
    """Every page, section by section in the tabs' order, each section in the
    order its navigation reads; then whatever is in no section."""
    seen = set()
    out = []
    for s in site.sections():
        for p in site.nav_tree_order(s["id"]):
            if p.url not in seen:
                seen.add(p.url)
                out.append(p)
    for p in site.pages:
        if p.url not in seen:
            seen.add(p.url)
            out.append(p)
    return out


def flat(url: str) -> str:
    return url.replace(".html", "").replace("/", "--")


def bundle(site) -> dict[str, bytes]:
    base = site.config["site"]["base_url"]
    title = site.config["site"]["title"]
    order = reading_order(site)
    section_titles = {s["id"]: s["title"] for s in site.sections()}
    out: dict[str, bytes] = {}
    texts = {}
    for p in order:
        text = page_markdown(p, base)
        texts[p.url] = text
        out[md_path(p.url)] = text.encode("utf-8")

    # llms.txt: the index, each page by its Markdown.
    lines = [f"# {title}", "",
             "> The documentation of raylib_multiplatform, a C++20 framework for shipping "
             "raylib games to every platform. Each link is one page as Markdown; "
             f"{base}llms-full.txt is all of them in one text.", ""]
    current = None
    for p in order:
        if p.section != current:
            current = p.section
            lines += ["", f"## {section_titles.get(current, 'Pages')}", ""]
        desc = f": {p.description}" if p.description else ""
        lines.append(f"- [{p.title}]({base}{md_path(p.url)}){desc}")
    out["llms.txt"] = ("\n".join(lines).strip() + "\n").encode("utf-8")

    # llms-full.txt: every page, in reading order.
    full = [f"# {title}: the whole documentation, in reading order", ""]
    for p in order:
        full += ["", "=" * 78, "", texts[p.url]]
    out["llms-full.txt"] = ("\n".join(full).strip() + "\n").encode("utf-8")

    # The zip: a folder per section, numbered in reading order, and an index.
    folders = {s["id"]: f"{i + 1:02d}-{s['id']}" for i, s in enumerate(site.sections())}
    index = [f"# {title}", "",
             "Every page of the documentation as Markdown, one folder per section, numbered "
             "in the order to read them. Each file starts with its title, a one-line summary "
             "and the address of the page on the web.", ""]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        counts: dict[str, int] = {}
        current = None
        for p in order:
            folder = folders.get(p.section, "99-other")
            counts[folder] = counts.get(folder, 0) + 1
            name = f"{folder}/{counts[folder]:03d}-{flat(p.url)}.md"
            if p.section != current:
                current = p.section
                index += ["", f"## {section_titles.get(current, 'Other pages')} (`{folder}/`)", ""]
            desc = f" -- {p.description}" if p.description else ""
            index.append(f"- `{name}`: {p.title}{desc}")
            info = zipfile.ZipInfo(f"rmp-docs/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            z.writestr(info, texts[p.url])
        info = zipfile.ZipInfo("rmp-docs/INDEX.md", date_time=(2026, 1, 1, 0, 0, 0))
        z.writestr(info, "\n".join(index).strip() + "\n")
    out["rmp-docs-ai.zip"] = buf.getvalue()

    out["print.html"] = print_page(site, order, base).encode("utf-8")
    return out


def print_page(site, order, base: str) -> str:
    """The manual in one page, to print or save as a PDF: every page but the
    generated API reference, its links made absolute."""
    title = site.config["site"]["title"]
    parts = []
    contents = []
    for i, p in enumerate(order):
        if p.section == "reference" or p.kind != "content" and p.section == "reference":
            continue
        body, _ = dom.parse(p.body or "")
        for n in body.walk():
            if isinstance(n, dom.Node):
                if n.get("href"):
                    n.attrs["href"] = absolute(n.get("href"), p.url, base)
                if n.get("src"):
                    n.attrs["src"] = absolute(n.get("src"), p.url, base)
                if n.get("id"):
                    n.attrs["id"] = f"p{i}-{n.get('id')}"
        anchor = f"page-{i}"
        contents.append(f'<li><a href="#{anchor}">{html.escape(p.title)}</a></li>')
        parts.append(f'<section class="print-page" id="{anchor}">'
                     f'<p class="print-source">{html.escape(base + p.url)}</p>'
                     f"{dom.serialize(body)}</section>")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}: the manual</title>
<link rel="stylesheet" href="assets/site.css">
<style>
  body {{ max-width: 46rem; margin: 2rem auto; padding: 0 1rem; }}
  .print-page {{ break-before: page; }}
  .print-source {{ font-size: .8rem; color: var(--text-muted, #666); }}
  .print-hint {{ border: 1px solid currentColor; padding: .75rem 1rem; border-radius: 6px; }}
  @media print {{ .print-hint {{ display: none; }} body {{ max-width: none; margin: 0; }} }}
</style>
<script>
  window.addEventListener("load", function () {{
    if (new URLSearchParams(location.search).has("print")) setTimeout(function () {{ window.print(); }}, 400);
  }});
</script>
</head>
<body>
<p class="print-hint">The whole manual in one page. Print it, or choose <em>Save as PDF</em> as the
printer. The API reference stays on the site: <a href="{base}reference/index.html">{base}reference/</a>.</p>
<h1>{html.escape(title)}</h1>
<p>{html.escape(base)} &mdash; documents raylib_multiplatform at {html.escape(site.ref[:8])}.</p>
<ol class="print-contents">{"".join(contents)}</ol>
{"".join(parts)}
</body>
</html>
"""
