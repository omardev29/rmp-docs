"""The examples: a page for every one the framework has, with its code, the
keys it reads, and -- for the ones a browser can run -- the example itself.

What is said about an example comes from the framework, not from here: its
summary is its row in examples/README.md, its code is its files, its keys
are the actions and keys its source reads. examples.toml only decides, per
example, whether it is played in the page, and says why when it is not.
"""

from __future__ import annotations

import html
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import prose
from .highlight import highlight

LANG = {".cpp": "cpp", ".h": "cpp", ".hpp": "cpp", ".c": "c"}


@dataclass
class Example:
    path: str                  # games/01_pong, plain_c
    title: str
    summary: str = ""          # markdown, from examples/README.md
    play: bool = False
    reason: str = ""
    files: list = field(default_factory=list)   # (relative path, text)
    keys: list = field(default_factory=list)    # (action or "", [keys])

    @property
    def target(self) -> str:
        return "example_" + self.path.replace("/", "_")

    @property
    def url(self) -> str:
        return f"examples/{self.path}.html"

    @property
    def area(self) -> str:
        return self.path.split("/", 1)[0] if "/" in self.path else ""


def find(framework: Path) -> list[str]:
    """Every example folder: one with a src/ of its own."""
    root = framework / "examples"
    out = []
    for src in sorted(root.glob("*/*/src")) + sorted(root.glob("*/src")):
        if src.is_dir():
            out.append(src.parent.relative_to(root).as_posix())
    return out


def title_of(path: str) -> str:
    if path == "plain_c":
        return "Plain C"
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r"^\d+_", "", name).replace("_", " ")
    return name[0].upper() + name[1:]


def readme_rows(framework: Path) -> dict[str, str]:
    """examples/README.md's table: the example a row links to -> its text."""
    text = (framework / "examples" / "README.md").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^\| \[[^\]]+\]\(([^)]+)\) \| (.+?) \|\s*$", text, re.M):
        link, body = m.group(1), m.group(2)
        path = re.sub(r"/src/.*$", "", link)
        if path == "main.c" or link.startswith("plain_c"):
            path = "plain_c"
        out[path] = body
    return out


INLINE_MD = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)\s]+)\)|`(?P<code>[^`]+)`")


def markdown_inline(text: str, framework_repo: str, ref: str) -> str:
    """The README's inline markdown: [text](link) -- whose text may hold
    `code` -- then `code`, then **bold**."""
    def plain(s: str) -> str:
        return html.escape(s, quote=False)

    def target(url: str) -> str:
        if url.startswith("http"):
            return url
        path = url
        while path.startswith("../"):
            path = path[3:]
        if not url.startswith("../"):
            path = "examples/" + path
        return f"{framework_repo}/tree/{ref}/{path}"

    out = []
    pos = 0
    for m in INLINE_MD.finditer(text):
        out.append(plain(text[pos:m.start()]))
        if m.group("code") is not None:
            out.append(f"<code>{html.escape(m.group('code'), quote=False)}</code>")
        else:
            label = markdown_inline(m.group("label"), framework_repo, ref)
            out.append(f'<a href="{html.escape(target(m.group("url")))}">{label}</a>')
        pos = m.end()
    out.append(plain(text[pos:]))
    # Bold last: its ** can sit on either side of a link.
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", "".join(out))


KEY_NAME = {"KEY_UP": "↑", "KEY_DOWN": "↓", "KEY_LEFT": "←", "KEY_RIGHT": "→",
            "KEY_SPACE": "Space", "KEY_ENTER": "Enter", "KEY_ESCAPE": "Esc",
            "KEY_LEFT_SHIFT": "Left Shift", "KEY_RIGHT_SHIFT": "Right Shift",
            "KEY_TAB": "Tab", "KEY_BACKSPACE": "Backspace"}


def key_label(k: str) -> str:
    if k in KEY_NAME:
        return KEY_NAME[k]
    if k.startswith("KEY_"):
        return k[4:].replace("_", " ").title() if len(k) > 5 else k[4:]
    if k.startswith("GAMEPAD_BUTTON_"):
        return "gamepad " + k[len("GAMEPAD_BUTTON_"):].lower().replace("_", " ")
    if k.startswith("MOUSE_BUTTON_"):
        return k[len("MOUSE_BUTTON_"):].lower() + " mouse button"
    return k


def keys_of(files) -> list:
    """(action, [keys]) for every rmp::input::action() the code defines, and
    ("", [keys]) for the keys it asks raylib about directly."""
    actions = []
    direct = []
    for _path, text in files:
        for m in re.finditer(r"rmp::input::action\(\s*\"([^\"]+)\"\s*,([^;]*?)\)\s*;", text, re.S):
            keys = re.findall(r"\b((?:KEY|GAMEPAD_BUTTON|MOUSE_BUTTON)_[A-Z0-9_]+)\b", m.group(2))
            if keys:
                actions.append((m.group(1), keys))
        for m in re.finditer(r"\bIs(?:Key|MouseButton|GamepadButton)(?:Pressed|Down|Released)\([^)]*?\b"
                             r"((?:KEY|MOUSE_BUTTON|GAMEPAD_BUTTON)_[A-Z0-9_]+)\)", text):
            if m.group(1) not in direct:
                direct.append(m.group(1))
    if direct:
        actions.append(("", direct))
    return actions


def load(framework: Path, config: dict) -> tuple[list[Example], list[str]]:
    """The examples, and every disagreement between examples.toml and the tree."""
    problems = []
    rows = readme_rows(framework)
    entries = config.get("examples", {})
    found = find(framework)
    out = []
    for path in found:
        spec = entries.get(path)
        if spec is None:
            problems.append(f"examples/{path} has no entry in examples.toml: play = true, or "
                            "play = false with the reason")
            spec = {"play": False, "reason": ""}
        if not spec.get("play") and not str(spec.get("reason", "")).strip():
            problems.append(f"examples.toml: {path} is not played and does not say why")
        folder = framework / "examples" / path
        files = []
        for f in sorted(folder.rglob("*")):
            if f.is_file() and f.suffix in LANG:
                files.append((f.relative_to(folder).as_posix(), f.read_text(encoding="utf-8")))
        files.sort(key=lambda x: (x[0] not in ("src/main.cpp", "src/main.c"), x[0]))
        ex = Example(path, title_of(path), summary=rows.get(path, ""), play=bool(spec.get("play")),
                     reason=str(spec.get("reason", "")), files=files, keys=keys_of(files))
        if not ex.summary:
            problems.append(f"examples/{path} has no row in examples/README.md to describe it")
        out.append(ex)
    for path in entries:
        if path not in found:
            problems.append(f"examples.toml names {path}, which is not an example of the framework")
    return out, problems


def poster_name(ex: Example) -> str:
    return f"{ex.target}.png"


def page_body(ex: Example, framework_repo: str, ref: str, built: dict, posters: set) -> str:
    out = [f"<h1>{html.escape(ex.title)}</h1>"]
    if ex.summary:
        out.append(f'<p class="lede">{markdown_inline(ex.summary, framework_repo, ref)}</p>')
    poster = poster_name(ex) if poster_name(ex) in posters else ""
    if ex.play and ex.target in built:
        size = built[ex.target]
        img = (f'<img src="/examples/posters/{poster}" alt="{html.escape(ex.title)}, as it starts" '
               f'width="800" height="450">' if poster else "")
        out.append(
            f'<div class="player" data-play="/examples/play/{ex.target}/index.html">{img}'
            f'<button class="play-button" type="button">Play — {size / 1e6:.1f} MB</button></div>')
    elif ex.play:
        out.append('<div class="callout warning"><span class="callout-title">Not built here</span>'
                   "<p>This build of the site was made without the examples' web builds, so the "
                   "example cannot be played on this page.</p></div>")
    else:
        if poster:
            out.append(f'<p><img src="/examples/posters/{poster}" alt="{html.escape(ex.title)}, as it '
                       f'starts" width="800" height="450"></p>')
        out.append('<div class="callout"><span class="callout-title">Not playable here</span>'
                   f"<p>{prose.inline(ex.reason)}</p></div>")
    name = ex.path.rsplit("/", 1)[-1] if ex.path != "plain_c" else "plain_c"
    out.append("<h2 id=\"run-it\">Run it</h2><p>From a clone of the framework:</p>"
               f'<pre data-lang="shell">rmp example {html.escape(name)}</pre>')
    if ex.keys:
        rows = "".join(
            f"<tr><td>{('<code>' + html.escape(a) + '</code>') if a else 'read directly'}</td>"
            f"<td>{', '.join('<kbd>' + html.escape(key_label(k)) + '</kbd>' for k in ks)}</td></tr>"
            for a, ks in ex.keys)
        out.append('<h2 id="keys">Keys</h2><p>Read from the code below: the actions it defines with '
                   "<code>rmp::input::action</code>, and the keys it asks raylib about directly.</p>"
                   f'<table class="fields"><thead><tr><th>Action</th><th>Keys</th></tr></thead>'
                   f"<tbody>{rows}</tbody></table>")
    out.append(f'<h2 id="code">The code</h2><p>Every file of <code>examples/{html.escape(ex.path)}</code>, '
               f'as it is at the commit this site documents '
               f'(<a href="{framework_repo}/tree/{ref}/examples/{ex.path}">on GitHub</a>).</p>')
    for i, (rel, text) in enumerate(ex.files):
        lang = LANG[Path(rel).suffix]
        url = f"{framework_repo}/blob/{ref}/examples/{ex.path}/{rel}"
        out.append(f'<details class="source"{" open" if i == 0 else ""}><summary><code>{html.escape(rel)}</code>'
                   f" <small>{text.count(chr(10))} lines</small></summary>"
                   f'<div class="code-block"><div class="code-head"><a class="file" href="{url}">'
                   f'{html.escape(rel)}</a><span class="spacer"></span></div>'
                   f'<pre data-lang="{lang}"><code>{highlight(text.rstrip(), lang)}</code></pre></div></details>')
    return "\n".join(out)


def gallery(examples: list[Example], posters: set, framework_repo: str, ref: str) -> str:
    areas: dict[str, list[Example]] = {}
    for ex in examples:
        areas.setdefault(ex.area or "plain C", []).append(ex)
    out = []
    for area, items in areas.items():
        out.append(f'<h2 id="area-{html.escape(area.replace(" ", "-"))}">{html.escape(area.capitalize() if area != "ui" else "UI")}</h2>')
        out.append('<div class="cards">')
        for ex in items:
            img = (f'<img src="/examples/posters/{poster_name(ex)}" alt="" width="400" height="225" loading="lazy">'
                   if poster_name(ex) in posters else "")
            tag = "playable" if ex.play else "source"
            summary = re.sub(r"<[^>]+>", "", markdown_inline(prose.first_sentence(ex.summary) or ex.summary,
                                                                 framework_repo, ref))
            out.append(f'<a class="card example-card" href="/{ex.url}">{img}<strong>{html.escape(ex.title)}</strong>'
                       f'<span class="badge">{tag}</span> <span>{summary}</span></a>')
        out.append("</div>")
    return "\n".join(out)


def copy_artifacts(examples: list[Example], web_dir: Path | None, posters_dir: Path | None,
                   out: Path, play_template: str) -> tuple[dict, set]:
    """Copy each playable example's web build and every poster into the site;
    (target -> download bytes, set of poster names)."""
    built = {}
    posters = set()
    if posters_dir is not None and posters_dir.is_dir():
        (out / "examples" / "posters").mkdir(parents=True, exist_ok=True)
        for ex in examples:
            src = posters_dir / f"{ex.target}.png"
            if src.is_file():
                shutil.copy(src, out / "examples" / "posters" / poster_name(ex))
                posters.add(poster_name(ex))
    if web_dir is not None and web_dir.is_dir():
        for ex in examples:
            if not ex.play:
                continue
            files = [web_dir / f"{ex.target}{ext}" for ext in (".js", ".wasm", ".data")]
            if not all(f.is_file() for f in files[:2]):
                continue
            dest = out / "examples" / "play" / ex.target
            dest.mkdir(parents=True, exist_ok=True)
            total = 0
            for f in files:
                if f.is_file():
                    shutil.copy(f, dest / f.name)
                    total += f.stat().st_size
            (dest / "index.html").write_text(
                play_template.replace("{{target}}", ex.target).replace("{{title}}", html.escape(ex.title)),
                encoding="utf-8")
            built[ex.target] = total
    return built, posters
