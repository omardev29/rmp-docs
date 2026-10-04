"""Header comments to HTML.

A comment in include/rmp/ is plain text with four conventions, and they are
all this understands:

  - a blank line separates paragraphs;
  - a block indented four spaces or more is code (C++), kept verbatim;
  - "- item" and "1. item" lines are lists, continuation lines indented;
  - any other indented block is text whose alignment matters (a small table
    written with spaces), kept in a monospace block as written;

and `backticks` mark code inside a sentence.
"""

from __future__ import annotations

import html
import re

from .highlight import highlight

INLINE_CODE = re.compile(r"`([^`\n]+)`")


# A name a header comment writes without backticks: rmp::input::pointer(),
# Scene::_draw(), BeginMode2D(camera.raylib()), [window] width.
BARE_CODE = re.compile(r"(?<![\w`])((?:rmp::|[A-Z]\w*::)[\w:~]+(?:\(\))?"
                       r"|[A-Za-z_]\w*(?:\.\w+)*\((?:[\w.:]*(?:\(\))?)?\)"
                       r"|\[[a-z_.]+\]\s[a-z_]+)(?![\w`])")


def backtick_bare(text: str) -> str:
    """Put backticks around code-shaped words that have none, outside the
    spans that already have them."""
    parts = re.split(r"(`[^`\n]+`)", text)
    for i in range(0, len(parts), 2):
        parts[i] = BARE_CODE.sub(lambda m: f"`{m.group(1)}`", parts[i])
    return "".join(parts)


def inline(text: str, link=None) -> str:
    """Escape a sentence and turn `x` into <code>x</code>, linked when
    `link(name)` returns a URL for it."""
    text = backtick_bare(text)
    # ASCII dashes, as the headers are written: " -- " is an em dash.
    text = re.sub(r"(?<=\s)--(?=\s)", "\u2014", text)
    out = []
    pos = 0
    for m in INLINE_CODE.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        code = m.group(1)
        url = link(code) if link else None
        span = f"<code>{html.escape(code, quote=False)}</code>"
        out.append(f'<a href="{html.escape(url)}">{span}</a>' if url else span)
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+[.)])\s+(.*)$")


def blocks(text: str) -> list[tuple[str, list[str]]]:
    """(kind, lines) for each block: para, code, list, ordered, aligned."""
    lines = text.split("\n")
    out: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _indent(line) >= 4 and not LIST_ITEM.match(line):
            block = []
            while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) >= 4):
                block.append(lines[i])
                i += 1
            while block and not block[-1].strip():
                block.pop()
            base = min(_indent(l) for l in block if l.strip())
            out.append(("code", [l[base:] for l in block]))
            continue
        m = LIST_ITEM.match(line)
        if m:
            ordered = m.group(2)[0].isdigit()
            base = len(m.group(1))
            items: list[list[str]] = []
            while i < len(lines):
                mm = LIST_ITEM.match(lines[i])
                if mm and len(mm.group(1)) == base:
                    items.append([mm.group(3)])
                elif lines[i].strip() and _indent(lines[i]) > base and items:
                    items[-1].append(lines[i].strip())
                else:
                    break
                i += 1
            out.append(("ordered" if ordered else "list", [" ".join(it) for it in items]))
            continue
        if _indent(line) >= 2:
            block = []
            while i < len(lines) and lines[i].strip() and _indent(lines[i]) >= 2 \
                    and not LIST_ITEM.match(lines[i]):
                block.append(lines[i])
                i += 1
            base = min(_indent(l) for l in block)
            out.append(("aligned", [l[base:] for l in block]))
            continue
        block = []
        while i < len(lines) and lines[i].strip() and _indent(lines[i]) < 2 \
                and not LIST_ITEM.match(lines[i]):
            block.append(lines[i].strip())
            i += 1
        out.append(("para", block))
    return out


def to_html(text: str, link=None) -> str:
    parts = []
    for kind, lines in blocks(text):
        if kind == "code":
            code = "\n".join(lines)
            parts.append('<div class="code-block"><pre data-lang="cpp"><code>'
                         + highlight(code, "cpp") + "</code></pre></div>")
        elif kind in ("list", "ordered"):
            tag = "ol" if kind == "ordered" else "ul"
            items = "".join(f"<li>{inline(it, link)}</li>" for it in lines)
            parts.append(f"<{tag}>{items}</{tag}>")
        elif kind == "aligned":
            parts.append('<div class="code-block"><pre data-lang="text"><code>'
                         + html.escape("\n".join(lines), quote=False) + "</code></pre></div>")
        else:
            parts.append(f"<p>{inline(' '.join(lines), link)}</p>")
    return "\n".join(parts)


def first_sentence(text: str) -> str:
    """The summary of a doc: its first sentence, for tables and search."""
    for kind, lines in blocks(text):
        if kind == "para":
            para = " ".join(lines)
            m = re.match(r"(.+?[.!?])(\s|$)", para)
            return (m.group(1) if m else para).strip()
    return ""
