"""Coverage: a page nobody can reach from the pages people read is a page
that might as well not exist.

The reference is generated, so it is complete by construction; the question
here is whether the hand-written pages -- the Manual, Getting started,
Publishing, the Framework section -- lead to all of it. A reader learns the
framework from the Manual and looks things up in the reference, and the
link between the two is what tells them a thing exists at all.

Read from the built pages, inside <article> only: the sidebar and the
section bar link everything and prove nothing.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse

from . import dom
from .checks import Context, Problem, _normalise, gate

GENERATED = ("reference/", "examples/")


def _article(root):
    for n in root.walk():
        if n.tag == "article":
            return n
    return None


def _written(ctx: Context):
    """(url, article) of every hand-written page."""
    for url, text in ctx.outputs.items():
        if url.startswith(GENERATED):
            continue
        root, _errors = dom.parse(text)
        article = _article(root)
        if article is not None:
            yield url, article


def _resolve(url: str, href: str) -> str | None:
    if re.match(r"[a-z][a-z0-9+.-]*:", href) or href.startswith("//"):
        return None
    path = urllib.parse.unquote(href.partition("#")[0])
    if not path:
        return url
    base = url.rsplit("/", 1)[0] if "/" in url else ""
    resolved = _normalise(f"{base}/{path}" if base else path)
    return resolved + "index.html" if resolved.endswith("/") or not resolved else resolved


def _run_json(ctx: Context, *argv):
    fw = ctx.framework
    got = subprocess.run([sys.executable, *argv], capture_output=True, text=True, cwd=fw)
    if got.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed in {fw}:\n{got.stdout}{got.stderr}")
    return json.loads(got.stdout)


@gate("coverage", "the pages people read lead to everything there is: every reference page "
                  "and every example is linked from a hand-written page, and every command "
                  "and every .toml section a game uses is shown on one")
def check_coverage(ctx: Context) -> list[Problem]:
    linked: set[str] = set()
    text = []
    for url, article in _written(ctx):
        for n in article.walk():
            href = n.attrs.get("href")
            if href is not None and n.tag == "a":
                target = _resolve(url, href)
                if target:
                    linked.add(target)
        text.append(article.text())
    said = "\n".join(text)

    out = []
    for url in sorted(ctx.outputs):
        if not url.startswith(GENERATED) or url.endswith("index.html"):
            continue
        if url not in linked:
            kind = "reference page" if url.startswith("reference/") else "example"
            out.append(Problem("coverage", url, 0,
                               f"no hand-written page links this {kind}: a reader who does not "
                               "already know it exists never finds it"))

    fw = ctx.framework
    if fw is None:
        return out
    if (fw / "tools" / "rmp.py").is_file():
        for c in _run_json(ctx, "tools/rmp.py", "help", "--json")["commands"]:
            if c.get("framework_only"):
                continue
            if not re.search(rf"\brmp\s+{re.escape(c['name'])}\b", said):
                out.append(Problem("coverage", f"rmp {c['name']}", 0,
                                   "no hand-written page shows this command"))
    if (fw / "tools" / "configure.py").is_file():
        sections = []
        for row in _run_json(ctx, "tools/configure.py", "--print-schema"):
            section = row["key"].rpartition(".")[0]
            if section not in sections:
                sections.append(section)
        for section in sections:
            if f"[{section}]" not in said:
                out.append(Problem("coverage", f"[{section}]", 0,
                                   "no hand-written page mentions this .toml section"))
    return out
