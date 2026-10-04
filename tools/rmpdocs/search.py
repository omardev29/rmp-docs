"""search.json: what the search box reads, built with the site.

One file, fetched the first time somebody opens the search, never before:

    docs      every page: title, url, section, its headings, a short excerpt
    symbols   every name in the reference: qualified name, url#anchor, kind,
              its first sentence
    index     token -> [[doc, weight], ...]: an inverted index of the pages

THE TOKENIZER IS THE CONTRACT. Python here and assets/js/search.js split text
the same way -- lowercase, then runs of [a-z0-9] -- so `rmp::ui::button`,
`updates_below` and "Updates below" all index and search as the same words.
tests/test_search.py holds both to it.
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict

TOKEN = re.compile(r"[a-z0-9]+")
STOP = set("a an and are as at be but by for from has have if in into is it its of on or "
           "so that the their them then there these they this to was what when which "
           "while who will with you your".split())


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def visible_text(body: str) -> str:
    body = re.sub(r"(?s)<(script|style|svg)\b.*?</\1>", " ", body)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(body)).strip()


def build(pages, reference_index, summaries) -> str:
    docs = []
    index: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for i, page in enumerate(pages):
        text = visible_text(page.body)
        headings = [t for _lvl, _id, t in page.toc]
        docs.append({"t": page.title, "u": page.url, "s": page.section,
                     "h": headings[:20], "x": page.description or text[:160]})
        for w in tokens(page.title):
            index[w][i] += 10
        for h in headings:
            for w in tokens(h):
                index[w][i] += 4
        for w in tokens(page.description):
            index[w][i] += 2
        for w in tokens(text):
            if w not in STOP and len(w) > 1:
                index[w][i] += 1
    symbols = []
    for name, url in sorted(reference_index.items()):
        kind, summary = summaries.get(name, ("", ""))
        symbols.append({"n": name, "u": url, "k": kind, "d": summary[:140]})
    compact = {w: sorted(([d, min(v, 99)] for d, v in hits.items()), key=lambda x: -x[1])
               for w, hits in sorted(index.items())}
    return json.dumps({"docs": docs, "symbols": symbols, "index": compact},
                      separators=(",", ":"), ensure_ascii=False)
