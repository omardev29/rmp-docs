"""Reference pages that come from the framework's tools, not its headers:

    reference/configuration.html   every .toml key   (configure.py --print-schema)
    reference/commands.html        every rmp command (rmp.py help --json)
    the defines table on reference/macros.html       (configure.py --print-defines)
    the targets table a page asks for                (configure.py --print-targets-table)

Run, not parsed: what the tool prints is what the tool does.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

from . import prose
from .highlight import highlight


def run_json(framework: Path, *argv) -> object:
    got = subprocess.run([sys.executable, *argv], capture_output=True, text=True, cwd=framework)
    if got.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed:\n{got.stdout}{got.stderr}")
    return json.loads(got.stdout)


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return str(v)


def key_anchor(key: str) -> str:
    return key.replace(".", "-")


def configuration_page(framework: Path) -> tuple[str, str, str]:
    rows = run_json(framework, "tools/configure.py", "--print-schema")
    sections: dict[str, list[dict]] = {}
    for r in rows:
        section, _, name = r["key"].rpartition(".")
        sections.setdefault(section, []).append(dict(r, name=name))
    out = ["<h1>Configuration</h1>",
           "<p class=\"lede\">Every key of <code>raylib_multiplatform.toml</code>: its default, what it "
           "takes, and what it is for. Read from <code>tools/configure.py --print-schema</code> at the "
           "commit this site documents; the explanations are the comments of the framework's own "
           ".toml.</p>",
           "<p>A key left out takes its default. A value <code>configure.py</code> refuses stops the "
           "build before anything is compiled, and the message names the line.</p>"]
    for section, keys in sections.items():
        sid = "section-" + section.replace(".", "-")
        out.append(f'<h2 id="{sid}"><code>[{html.escape(section)}]</code></h2>')
        for k in keys:
            kid = key_anchor(k["key"])
            out.append(f'<section class="entity" id="{kid}"><h3><code>{html.escape(k["name"])}</code></h3>')
            sig = f"{k['name']} = {toml_value(k['default'])}"
            out.append(f'<div class="signature">{highlight(sig, "toml")}</div>')
            meta = [f'<span class="badge">{html.escape(k["type"])}</span>']
            if "allowed" in k:
                meta.append("one of " + ", ".join(f"<code>{html.escape(toml_value(a))}</code>"
                                                  for a in k["allowed"]))
            if "allowed_items" in k:
                items = k["allowed_items"]
                shown = ", ".join(f"<code>{html.escape(a)}</code>" for a in items[:12])
                more = f" and {len(items) - 12} more" if len(items) > 12 else ""
                meta.append(f"a list of {shown}{more}")
            out.append(f'<div class="entity-meta">{" ".join(meta)}</div>')
            if k["comment"]:
                out.append(prose.to_html(k["comment"]))
            out.append("</section>")
    return ("reference/configuration.html", "Configuration", "\n".join(out))


def commands_page(framework: Path) -> tuple[str, str, str]:
    data = run_json(framework, "tools/rmp.py", "help", "--json")
    out = ["<h1>Commands</h1>",
           "<p class=\"lede\">Every <code>rmp</code> command, as <code>rmp help</code> describes it at "
           "the commit this site documents. <code>rmp help &lt;command&gt;</code> prints the same "
           "page in a terminal.</p>"]
    game = [c for c in data["commands"] if not c["framework_only"]]
    framework_only = [c for c in data["commands"] if c["framework_only"]]
    for title, group in (("For a game", game), ("In the framework's own repository", framework_only)):
        if not group:
            continue
        out.append(f'<h2 id="{"game" if group is game else "framework"}">{title}</h2>')
        for c in group:
            out.append(f'<section class="entity" id="{html.escape(c["name"])}">'
                       f"<h3><code>rmp {html.escape(c['usage'])}</code></h3>")
            out.append(f"<p>{prose.inline(c['sentence'])}</p>")
            rows = "".join(f"<tr><td><code>{html.escape(e['line'])}</code></td>"
                           f"<td>{prose.inline(e['note'])}</td></tr>" for e in c["examples"])
            out.append(f'<table class="fields"><tbody>{rows}</tbody></table>')
            if c["name"] == "test":
                stages = "".join(
                    f"<tr><td><code>{html.escape(s['name'])}</code></td>"
                    f"<td>{prose.inline(s['summary'])}</td>"
                    f"<td>{'game and framework' if s['scope'] == 'both' else s['scope']}</td>"
                    f"<td>{'yes' if s['in_all'] else 'only by name'}</td></tr>"
                    for s in data["stages"])
                out.append('<p>Its stages, in the order <code>rmp test</code> runs them:</p>'
                           '<table class="fields"><thead><tr><th>Stage</th><th>Checks</th>'
                           '<th>In</th><th>In <code>rmp test</code></th></tr></thead>'
                           f"<tbody>{stages}</tbody></table>")
            out.append("</section>")
    return ("reference/commands.html", "Commands", "\n".join(out))


def defines_table(framework: Path) -> str:
    rows = run_json(framework, "tools/configure.py", "--print-defines")
    body = "".join(
        f'<tr id="toml-{html.escape(d["name"])}"><td><code>{html.escape(d["name"])}</code></td>'
        f'<td><a href="/reference/configuration.html#{key_anchor(d["key"])}"><code>'
        f'[{html.escape(d["key"].rsplit(".", 1)[0])}] {html.escape(d["key"].rsplit(".", 1)[1])}'
        f"</code></a></td><td><code>{html.escape(d['value'])}</code></td></tr>"
        for d in rows)
    return ('<h2 id="from-the-toml">Set by the .toml</h2>'
            "<p>Every value of <code>raylib_multiplatform.toml</code> a game can read in C or C++ is a "
            "macro of the generated <code>rmp/config.h</code>, which every public header includes. "
            "The values here are the framework's own; a game's are whatever its .toml says.</p>"
            '<table class="fields"><thead><tr><th>Macro</th><th>From</th><th>The framework\'s value</th>'
            f"</tr></thead><tbody>{body}</tbody></table>")


def build_defines_table(framework: Path, refconf: dict) -> tuple[str, list[str]]:
    """reference.toml [build_defines]: macros the build passes, each checked
    against the files it says set it. Returns the table and what is wrong."""
    rows, wrong = [], []
    for name, spec in refconf.get("build_defines", {}).items():
        for rel in spec.get("set_in", []):
            f = framework / rel
            if not f.is_file() or not re.search(rf"\b{re.escape(name)}=", f.read_text(encoding="utf-8")):
                wrong.append(f"[build_defines] {name}: {rel} does not set it ({name}=...)")
        if not spec.get("set_in"):
            wrong.append(f"[build_defines] {name}: says no file that sets it (set_in)")
        rows.append(f'<tr id="{html.escape(name)}"><td><code>{html.escape(name)}</code></td>'
                    f"<td>{prose.inline(spec.get('doc', ''))}</td></tr>")
    if not rows:
        return "", wrong
    return ('<h2 id="from-the-build">Set by the build</h2>'
            "<p>Macros no header defines: the build passes them to the compiler, for the framework "
            "and for your game.</p>"
            '<table class="fields"><thead><tr><th>Macro</th><th>What it is</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table>"), wrong


def targets_table(framework: Path) -> str:
    rows = run_json(framework, "tools/configure.py", "--print-targets-table")
    body = "".join(
        f"<tr><td><code>{html.escape(r['id'])}</code></td><td>{html.escape(r['name'])}</td>"
        f"<td>{html.escape(r['family'])}</td>"
        f"<td>{', '.join('<code>' + html.escape(g) + '</code>' for g in r['groups'])}</td></tr>"
        for r in rows)
    return ('<table class="fields"><thead><tr><th>Target</th><th>What it is</th><th>Family</th>'
            f"<th>Groups it is in</th></tr></thead><tbody>{body}</tbody></table>")


GENERATED_BLOCKS = {"targets-table": targets_table}
