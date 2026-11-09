"""tools/rmpdocs/export.py: a page as Markdown, and what the site gives a reader
to take away -- llms.txt, llms-full.txt, the zip for an AI and the page to print
-- on a small site made here."""

import io
import sys
import unittest
import zipfile
from dataclasses import dataclass
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import export  # noqa: E402

BASE = "https://example.org/docs/"

BODY = """<h1>Dialogue</h1>
<p>A <strong>conversation</strong> in <code>.yarn</code>, run by
<a href="../../reference/x.html#start">start()</a> and <a href="#waiting">a wait</a>.</p>
<h2 id="waiting">Waiting<a class="heading-anchor" href="#waiting">#</a></h2>
<pre data-lang="cpp"><code>if (a &lt; b) talk.wait(2);</code></pre>
<ul><li>one <em>thing</em></li><li>two<ul><li>inner</li></ul></li></ul>
<ol><li>first</li><li>second</li></ol>
<table><thead><tr><th>Name</th><th>What</th></tr></thead>
<tbody><tr><td><code>a|b</code></td><td>pipes</td></tr></tbody></table>
<script>never()</script>
<p>External <a href="https://example.com/x">site</a>.</p>
<p><img src="poster.png" alt="A poster"></p>"""


@dataclass
class Page:
    url: str
    title: str
    description: str
    section: str
    body: str
    kind: str = "content"


class FakeSite:
    def __init__(self):
        self.config = {"site": {"base_url": BASE, "title": "Docs"}}
        self.ref = "0123456789abcdef0123456789abcdef01234567"
        self.pages = [
            Page("manual/modules/dialogue.html", "Dialogue", "Talk to people.", "manual", BODY),
            Page("manual/index.html", "Manual", "Every part.", "manual", "<h1>Manual</h1><p>Hi.</p>"),
            Page("reference/index.html", "Reference", "", "reference",
                 "<h1>Reference</h1><p>API.</p>"),
            Page("index.html", "Home", "", "", "<h1>Home</h1>"),
        ]

    def sections(self):
        return [{"id": "manual", "title": "Manual"}, {"id": "reference", "title": "Reference"}]

    def nav_tree_order(self, section):
        order = {"manual": ["manual/index.html", "manual/modules/dialogue.html"],
                 "reference": ["reference/index.html"]}[section]
        return [next(p for p in self.pages if p.url == u) for u in order]


class MarkdownTest(unittest.TestCase):
    def setUp(self):
        self.md = export.page_markdown(FakeSite().pages[0], BASE)

    def test_title_summary_and_address_first(self):
        self.assertTrue(self.md.startswith("# Dialogue\n\n> Talk to people.\n\nSource: "
                                           f"{BASE}manual/modules/dialogue.html\n"))
        self.assertEqual(self.md.count("# Dialogue"), 1)

    def test_inline_marks_and_absolute_links(self):
        self.assertIn("A **conversation** in `.yarn`, run by "
                      f"[start()]({BASE}reference/x.html#start) and "
                      f"[a wait]({BASE}manual/modules/dialogue.html#waiting).", self.md)
        self.assertIn("[site](https://example.com/x)", self.md)

    def test_headings_without_their_anchor(self):
        self.assertIn("\n## Waiting\n", self.md)
        self.assertNotIn("[#]", self.md)

    def test_code_keeps_its_language_and_its_characters(self):
        self.assertIn("```cpp\nif (a < b) talk.wait(2);\n```", self.md)

    def test_lists_nested_and_numbered(self):
        self.assertIn("- one *thing*\n- two\n  - inner", self.md)
        self.assertIn("1. first\n2. second", self.md)

    def test_tables_with_their_pipes_escaped(self):
        self.assertIn("| Name | What |\n|---|---|\n| `a\\|b` | pipes |", self.md)

    def test_scripts_are_left_out(self):
        self.assertNotIn("never()", self.md)

    def test_paths(self):
        self.assertEqual(export.md_path("manual/modules/dialogue.html"),
                         "ai/manual/modules/dialogue.md")
        self.assertEqual(export.absolute("../a/", "x/y/z.html", BASE), BASE + "x/a/index.html")
        self.assertEqual(export.absolute("/b.html#c", "x/y.html", BASE), BASE + "b.html#c")


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.out = export.bundle(FakeSite())

    def test_every_page_has_its_markdown(self):
        for url in ("manual/modules/dialogue.html", "manual/index.html", "reference/index.html",
                    "index.html"):
            self.assertIn(export.md_path(url), self.out)

    def test_llms_txt_is_the_index_in_reading_order(self):
        text = self.out["llms.txt"].decode()
        self.assertTrue(text.startswith("# Docs\n\n> "))
        manual = text.index(f"[Manual]({BASE}ai/manual/index.md): Every part.")
        dialogue = text.index(f"[Dialogue]({BASE}ai/manual/modules/dialogue.md): Talk to people.")
        reference = text.index("## Reference")
        self.assertLess(manual, dialogue)
        self.assertLess(dialogue, reference)

    def test_llms_full_is_every_page_once(self):
        text = self.out["llms-full.txt"].decode()
        for title in ("# Manual", "# Dialogue", "# Reference", "# Home"):
            self.assertEqual(text.count(f"\n{title}\n"), 1, title)

    def test_the_zip_is_a_folder_per_section_in_order(self):
        z = zipfile.ZipFile(io.BytesIO(self.out["rmp-docs-ai.zip"]))
        names = z.namelist()
        self.assertEqual(names, ["rmp-docs/01-manual/001-manual--index.md",
                                 "rmp-docs/01-manual/002-manual--modules--dialogue.md",
                                 "rmp-docs/02-reference/001-reference--index.md",
                                 "rmp-docs/99-other/001-index.md",
                                 "rmp-docs/INDEX.md"])
        index = z.read("rmp-docs/INDEX.md").decode()
        self.assertIn("`01-manual/002-manual--modules--dialogue.md`: Dialogue -- Talk to people.",
                      index)

    def test_the_zip_is_the_same_bytes_every_build(self):
        self.assertEqual(self.out["rmp-docs-ai.zip"], export.bundle(FakeSite())["rmp-docs-ai.zip"])

    def test_the_print_page_is_the_manual_without_the_reference(self):
        page = self.out["print.html"].decode()
        self.assertIn("<h1>Dialogue</h1>", page)
        self.assertNotIn("<h1>Reference</h1>", page)
        # Relative to the site's root, where print.html is: the browser check
        # opens the built site with no network, and an address of the live
        # site there was a request that failed (every example's poster).
        self.assertIn('href="reference/x.html#start"', page)
        self.assertIn('src="manual/modules/poster.png"', page)
        self.assertNotIn(f'src="{BASE}', page)
        # Its own icon, as every page has, or the browser asks for
        # /favicon.ico and the browser check reads a 404 in the console.
        self.assertIn('<link rel="icon" href="assets/icon.svg"', page)
        self.assertIn('id="p1-waiting"', page)


if __name__ == "__main__":
    unittest.main()
