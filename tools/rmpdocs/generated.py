"""Reference pages that come from the framework's tools, not its headers:

    reference/configuration.html   every .toml key   (configure.py --print-schema)
    reference/commands.html        every rmp command (rmp.py help --json)
    the defines table on reference/macros.html       (configure.py --print-defines)
    the targets table a page asks for                (configure.py --print-targets-table)
    the pinned versions and the dependency map       (FROZEN_VERSIONS.md, and every tracked file)

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


def config_comments(rows: list[dict], refconf: dict) -> list[str]:
    """reference.toml [config_comment."section.key"]: a key whose comment in the
    framework's .toml says what the framework at FRAMEWORK_REF does not do. The
    page shows `comment` instead -- and only while the framework's own comment
    still starts with `replaces`: the day it changes, the build says so, and
    whoever bumps FRAMEWORK_REF reads the new one and drops the entry when it
    has become true. Rewrites `rows` in place; returns what is wrong."""
    wrong = []
    by_key = {r["key"]: r for r in rows}
    for key, spec in refconf.get("config_comment", {}).items():
        where = f'[config_comment."{key}"]'
        if not isinstance(spec, dict):
            wrong.append(f"{where}: a table, with replaces, comment and reason")
            continue
        missing = [f for f in ("replaces", "comment", "reason") if not str(spec.get(f, "")).strip()]
        if missing:
            wrong.append(f"{where}: no {', '.join(missing)}")
            continue
        row = by_key.get(key)
        if row is None:
            wrong.append(f"{where}: the .toml has no key {key}")
            continue
        if not row["comment"].startswith(spec["replaces"]):
            wrong.append(f"{where}: the framework's comment no longer starts with "
                         f"{spec['replaces']!r}. Read what it says now, and drop the entry if it is "
                         "true of the framework at FRAMEWORK_REF:\n" + row["comment"])
            continue
        row["comment"] = spec["comment"].strip()
    return wrong


def config_see(rows: list[dict], refconf: dict) -> tuple[dict, list[str]]:
    """reference.toml [config_see."section.key"]: a page that says more about
    a key than its comment can -- what it catches, what configure.py refuses,
    with the refusal shown. {key: (href, says)}, and what is wrong: a key the
    .toml does not have, or an entry without both. The link itself is the
    links gate's, like every link of the site."""
    keys = {r["key"] for r in rows}
    out, wrong = {}, []
    for key, spec in refconf.get("config_see", {}).items():
        where = f'[config_see."{key}"]'
        if key not in keys:
            wrong.append(f"{where}: the .toml has no key {key}")
            continue
        if not isinstance(spec, dict) or not str(spec.get("href", "")).startswith("/") \
                or not str(spec.get("says", "")).strip():
            wrong.append(f"{where}: an href inside the site (/...) and what the page says (says)")
            continue
        out[key] = (spec["href"], spec["says"].strip())
    return out, wrong


def configuration_page(framework: Path, refconf: dict | None = None,
                       wrong: list | None = None) -> tuple[str, str, str]:
    rows = run_json(framework, "tools/configure.py", "--print-schema")
    problems = config_comments(rows, refconf or {})
    see, see_wrong = config_see(rows, refconf or {})
    problems += see_wrong
    if wrong is not None:
        wrong.extend(problems)
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
            if k["key"] in see:
                href, says = see[k["key"]]
                out.append(f'<p>See <a href="{html.escape(href)}">{prose.inline(says)}</a>.</p>')
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


# What a name of [build_switches] looks like in the file that reads it. An
# environment variable: CMake's $ENV{X}, C's getenv("X"), Python's
# os.environ.get("X") or a module constant the code reads it through
# (`DRM_ENV = "RMP_DRM"`), a workflow's `X:` and a shell script's ${X} or $X.
SWITCH_KINDS = {
    "cmake option": ("a CMake option", lambda n: rf"\boption\(\s*{re.escape(n)}\b"),
    "environment": ("an environment variable",
                    lambda n: rf"\$ENV\{{{re.escape(n)}\}}|getenv\(\s*\"{re.escape(n)}\"|"
                              rf"environ(?:\.get\(|\[)\s*[\"']{re.escape(n)}[\"']|"
                              rf"^[A-Z][A-Z0-9_]*\s*=\s*\"{re.escape(n)}\"\s*$|"
                              rf"\$\{{{re.escape(n)}(?::?[-=?+][^}}]*)?\}}|\${re.escape(n)}\b|"
                              rf"^\s*{re.escape(n)}:\s"),
}


def build_switches_table(framework: Path, refconf: dict) -> tuple[str, list[str]]:
    """reference.toml [build_switches]: RMP_ names the build reads that are not
    macros -- a CMake option, an environment variable -- each checked against
    the files it says read it, by the shape its kind has there. Returns the
    table and what is wrong."""
    rows, wrong = [], []
    for name, spec in refconf.get("build_switches", {}).items():
        kind = spec.get("kind", "")
        if kind not in SWITCH_KINDS:
            wrong.append(f"[build_switches] {name}: kind is {kind!r}, not one of "
                         f"{', '.join(repr(k) for k in SWITCH_KINDS)}")
            continue
        what, shape = SWITCH_KINDS[kind]
        if not spec.get("read_in"):
            wrong.append(f"[build_switches] {name}: says no file that reads it (read_in)")
        for rel in spec.get("read_in", []):
            f = framework / rel
            if not f.is_file() or not re.search(shape(name), f.read_text(encoding="utf-8"), re.M):
                wrong.append(f"[build_switches] {name}: {rel} does not read it as {what}")
        rows.append(f'<tr id="{html.escape(name)}"><td><code>{html.escape(name)}</code></td>'
                    f"<td>{html.escape(what)}</td><td>{prose.inline(spec.get('doc', ''))}</td></tr>")
    if not rows:
        return "", wrong
    return ('<h2 id="read-by-the-build">Read by the build</h2>'
            "<p>Names that are not macros at all: switches of the build itself, given to CMake with "
            "<code>-D</code> or set in the environment.</p>"
            '<table class="fields"><thead><tr><th>Name</th><th>Is</th><th>What it does</th></tr>'
            f"</thead><tbody>{''.join(rows)}</tbody></table>"), wrong


def targets_table(framework: Path) -> str:
    rows = run_json(framework, "tools/configure.py", "--print-targets-table")
    body = "".join(
        f"<tr><td><code>{html.escape(r['id'])}</code></td><td>{html.escape(r['name'])}</td>"
        f"<td>{html.escape(r['family'])}</td>"
        f"<td>{', '.join('<code>' + html.escape(g) + '</code>' for g in r['groups'])}</td></tr>"
        for r in rows)
    return ('<table class="fields"><thead><tr><th>Target</th><th>What it is</th><th>Family</th>'
            f"<th>Groups it is in</th></tr></thead><tbody>{body}</tbody></table>")


def size_budget_table(framework: Path) -> str:
    """tools/size_budget.txt as a table: every binary a release ships, unpacked
    and packed, as its line says -- the numbers the size budget holds a
    release to, never typed into a page that goes stale at the next growth."""
    rows = []
    for line in (framework / "tools" / "size_budget.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields, _, comment = line.partition("#")
        parts = fields.split()
        if len(parts) != 4:
            continue
        name, _kind, unpacked, packed = parts

        def number(v: str) -> str:
            return f"{int(v):,}" if v.isdigit() else ("not measured yet" if v == "?" else "\u2014")

        size = number(unpacked)
        if "estimate" in comment.lower() and unpacked.isdigit():
            size += ", an estimate"
        rows.append(f"<tr><td><code>{html.escape(name)}</code></td><td>{html.escape(size)}</td>"
                    f"<td>{html.escape(number(packed))}</td></tr>")
    return ('<table><thead><tr><th>Binary</th><th>Unpacked, bytes</th><th>Packed, bytes</th></tr>'
            f"</thead><tbody>{''.join(rows)}</tbody></table>")


def versions_block(framework: Path) -> list[tuple[str, str, str]]:
    """The ```versions block of thirdparty/FROZEN_VERSIONS.md as (key, value,
    the comment above it), in order: the comment is the run of # lines that
    came before the key, and holds for every key up to the next comment."""
    rows, inside, comment, fresh = [], False, [], False
    for line in (framework / "thirdparty" / "FROZEN_VERSIONS.md").read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\r")
        if line.strip() == "```versions":
            inside = True
            continue
        if not inside:
            continue
        if line.strip() == "```":
            break
        text = line.strip()
        if not text:
            continue
        if text.startswith("#"):
            if not fresh:
                comment, fresh = [], True
            comment.append(text.lstrip("#").strip())
            continue
        fresh = False
        key, _, value = text.partition(" ")
        rows.append((key, value.strip(), " ".join(comment)))
    return rows


def versions_table(framework: Path) -> str:
    """Every pin of the ```versions block, as tools/versions_check.sh reads it:
    the one list a bump changes first, never retyped into a page."""
    body = []
    for key, value, _comment in versions_block(framework):
        shown = value
        digest = re.fullmatch(r"(sha256:)?([0-9a-f]{64})", value)
        if digest:
            shown = (digest.group(1) or "") + digest.group(2)[:16] + "…"
        body.append(f"<tr><td><code>{html.escape(key)}</code></td><td><code>{html.escape(shown)}</code></td></tr>")
    return ('<table><thead><tr><th>Key</th><th>Pinned to</th></tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table>")


# Every dependency the framework has, what it is, where its version is held,
# and the regex that means a file uses it. The map on
# framework/maintaining/dependencies.html is read from the tracked files at
# FRAMEWORK_REF with these, so "if I change X, what else do I look at?" is
# answered by the tree and not by a list typed once.
DEPENDENCIES = (
    ("raylib", "the window, input, audio and renderer; a modified copy", "the committed files, and PATCHES.md",
     r"\b(?:raylib\.h|raymath\.h|rlgl\.h|rlsw\.h|rcore_\w+)\b|thirdparty/raylib(?![\w-])"),
    ("raylib-cpp", "the math types only: vectors, matrices, rectangles, colours", "the committed files",
     r"raylib-cpp|\braylib::\w"),
    ("raymob", "Android's native glue and its Java side; patched", "the committed files, and PATCHES.md",
     r"raymob|Raymob|AdmobBridge|NativeLoader|GetAndroidApp"),
    ("raylib-iOS", "the iOS backend, UIKit and EGL through ANGLE; a fork of a fork", "the submodule's commit",
     r"raylib-ios|raylib-iOS|rcore_ios|\bANGLE\b|libEGL\.xcframework"),
    ("Clay", "the UI's layout engine, used only under src/rmp/ui/", "the committed file, and PATCHES.md",
     r"\bclay\.h|\bClay_\w+|\bCLAY_\w+|thirdparty/clay"),
    ("cute_tiled", "the Tiled map reader; patched and hardened", "the committed file, and PATCHES.md",
     r"cute_tiled"),
    ("cute_aseprite", "the Aseprite reader", "sha256_cute_aseprite", r"cute_aseprite"),
    ("cJSON", "JSON, for saves and LDtk", "sha256_cjson", r"\bcJSON"),
    ("rres", "the resource pack, its compression and its encryption", "sha256_rres",
     r"\brres\b|rres\.h|rres-raylib|rres_pack"),
    ("doctest", "the unit test framework, shipped with every game's tests", "sha256_doctest", r"doctest"),
    ("RapidCheck", "the C++ property tests; the framework's only", "sha256_rapidcheck",
     r"rapidcheck|RapidCheck|\bRC_ASSERT\b"),
    ("Android build stack", "Gradle, AGP, the SDK, the NDK and AdMob's SDK", "android_*, agp, gradle, play_services_ads",
     r"gradle|Gradle|android_ndk|android_platform|android_build_tools|play_services_ads|\bAGP\b|\bagp\b"),
    ("Apple toolchain", "Xcode, XcodeGen and the macOS runner", "xcode, xcodegen, macos_runner",
     r"\bXcode\b|xcodebuild|xcode-select|XcodeGen|xcodegen|\bmacos-\d+"),
    ("Emscripten", "the web build's compiler", "emscripten, and the image's emsdk commit",
     r"[Ee]mscripten|EMSCRIPTEN|emsdk|\bemcc\b|\bemcmake\b"),
    ("zig", "the Linux cross-compiler that sets the glibc floor", "zig, zig_sha256_*", r"\bzig\b"),
    ("The build image", "every Linux, web and Android job's toolchain", "build_image_digest",
     r"raylib-build(?![\w-])|build_image_digest|raylib-build-image|dev_shell\.sh|PINNED_IMAGE"),
    ("LLVM test tools", "coverage, the sanitizers' runtimes, libFuzzer and Mull", "llvm, mull",
     r"\bMull\b|mull-runner|compiler-rt|llvm-cov|llvm-profdata|libFuzzer|\bllvm-\d+"),
    ("clang-format and clang-tidy", "the formatter and the linter", "clang_format, clang_tidy",
     r"clang-format|clang-tidy|clang_format|clang_tidy"),
    ("Python test tools", "Hypothesis, mutmut and pytest", "hypothesis, mutmut, pytest",
     r"\bhypothesis\b|Hypothesis|\bmutmut\b|\bpytest\b"),
    ("Pillow", "the icons: the .ico, Android's and iOS's", "pillow, pillow_sha256_*", r"\bPIL\b|Pillow|\bpillow\b"),
    ("PyYAML", "the workflow checks read the YAML with it", "the image's apt snapshot", r"\byaml\b|PyYAML"),
    ("Playwright", "the web boot test's browser", "package-lock.json", r"[Pp]laywright"),
    ("BSD virtual machines", "FreeBSD, OpenBSD and NetBSD, started by cross-platform-actions",
     "freebsd, openbsd, netbsd", r"cross-platform-actions|\bfreebsd\b|\bopenbsd\b|\bnetbsd\b"),
)

MAP_SKIP_PREFIXES = ("tests/fuzz/corpus/", "tests/fuzz/regressions/", "tests/e2e/golden/",
                     "tests/mutation/floors/", "thirdparty/")
MAP_SKIP_SUFFIXES = (".png", ".jpg", ".ico", ".icns", ".ttf", ".wav", ".ogg", ".mp3", ".qoa", ".aseprite",
                     ".rres", ".zip", ".jar", ".a", ".ldtk", ".tmj", ".bin", ".gz")
MAP_KEEP = ("thirdparty/FROZEN_VERSIONS.md",)
MAP_CATEGORIES = ("Product code", "Build projects", "Tools and gates", "Tests", "CI", "Examples",
                  "Docs, pins and config", "This site", "Other")
DOCS_ROOT = Path(__file__).resolve().parents[2]


def dep_anchor(name: str) -> str:
    """The id of a dependency's entry in the map: "dep-" and its name, lower case, dashed."""
    return "dep-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def map_category(path: str) -> str:
    """Where a tracked file sits, in the words of the map's columns."""
    if path.startswith(("src/", "include/")):
        return "Product code"
    if path.startswith("examples/"):
        return "Examples"
    if path.startswith("tests/"):
        return "Tests"
    if path.startswith("tools/"):
        return "Tools and gates"
    if path.startswith(".github/"):
        return "CI"
    if path in ("CMakeLists.txt", "CMakePresets.json") or path.startswith(("cmake/", "raymob/", "ios/")):
        return "Build projects"
    if path.endswith((".md", ".toml", ".txt")):
        return "Docs, pins and config"
    return "Other"


def tracked_files(root: Path) -> list[str]:
    """The files git tracks under root, or, out of a checkout, every file."""
    got = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True)
    if got.returncode == 0 and got.stdout.strip():
        return got.stdout.splitlines()
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)


def map_texts(framework: Path, docs: Path | None) -> dict[str, str]:
    """Path -> text of every file the map reads: the framework's own files (a
    vendored library's are not users of it, but the pins are), and this site's
    pages but the ones about the map, which name everything on purpose."""
    texts = {}
    for rel in tracked_files(framework):
        if rel.endswith(MAP_SKIP_SUFFIXES) or (rel.startswith(MAP_SKIP_PREFIXES) and rel not in MAP_KEEP
                                               and not rel.endswith("/PATCHES.md")):
            continue
        try:
            texts[rel] = (framework / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    if docs is not None and (docs / "content").is_dir():
        for page in sorted((docs / "content").rglob("*.html")):
            rel = page.relative_to(docs).as_posix()
            if rel.startswith("content/framework/maintaining/"):
                continue
            texts["rmp-docs:" + rel] = page.read_text(encoding="utf-8", errors="ignore")
    return texts


def dependency_uses(texts: dict[str, str]) -> list[tuple[tuple, dict[str, list[tuple[str, int]]]]]:
    """For each dependency, its files by category, the most mentions first."""
    out = []
    for dep in DEPENDENCIES:
        pattern = re.compile(dep[3])
        by_cat: dict[str, list[tuple[str, int]]] = {}
        for rel, text in texts.items():
            n = len(pattern.findall(text))
            if not n:
                continue
            if rel.startswith("rmp-docs:"):
                by_cat.setdefault("This site", []).append((rel.removeprefix("rmp-docs:content/"), n))
            else:
                by_cat.setdefault(map_category(rel), []).append((rel, n))
        for files in by_cat.values():
            files.sort(key=lambda f: (-f[1], f[0]))
        out.append((dep, by_cat))
    return out


def dependency_map(framework: Path, docs: Path | None = DOCS_ROOT) -> str:
    """framework/maintaining/dependencies.html's map: per dependency, how many
    files of each kind name it, then every one of them with how often."""
    uses = dependency_uses(map_texts(framework, docs))
    columns = ("Product code", "Build projects", "Tools and gates", "Tests", "CI", "Examples")
    head = "".join(f"<th>{c}</th>" for c in columns)
    summary = []
    for dep, by_cat in uses:
        docs_n = len(by_cat.get("Docs, pins and config", [])) + len(by_cat.get("This site", []))
        cells = "".join(f"<td>{len(by_cat.get(c, []))}</td>" for c in columns)
        summary.append(f'<tr><td><a href="#{dep_anchor(dep[0])}">{html.escape(dep[0])}</a></td>'
                       f"{cells}<td>{docs_n}</td></tr>")
    detail = []
    for dep, by_cat in uses:
        items = []
        for cat in MAP_CATEGORIES:
            files = by_cat.get(cat)
            if not files:
                continue
            names = ", ".join(f"<code>{html.escape(f)}</code>&#160;({n})" for f, n in files)
            items.append(f"<li><strong>{cat}</strong> ({len(files)}): {names}</li>")
        total = sum(len(v) for v in by_cat.values())
        detail.append(f'<details class="source" id="{dep_anchor(dep[0])}"><summary>{html.escape(dep[0])}'
                      f"<small>{total} files</small></summary>"
                      f"<p>{html.escape(dep[1])}. Its version: {html.escape(dep[2])}.</p>"
                      f"<ul>{''.join(items) or '<li>no file names it</li>'}</ul></details>")
    return (f'<table><thead><tr><th>Dependency</th>{head}<th>Docs</th></tr></thead>'
            f"<tbody>{''.join(summary)}</tbody></table>" + "".join(detail))


GENERATED_BLOCKS = {"targets-table": targets_table, "size-budget-table": size_budget_table,
                    "versions-table": versions_table, "dependency-map": dependency_map}
