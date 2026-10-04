"""Gates on what the pages SAY about the framework: the commands they show
exist, the names they write resolve, the paths they mention are there, the
claims they pin to the source still hold, and no picture is a stale one.

Each reads the content fragments (the page's own words, not the generated
reference) and the framework at FRAMEWORK_REF.
"""

from __future__ import annotations

import functools
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from . import dom
from .checks import Context, Problem, gate


def _fragments(ctx: Context):
    """(path, root) of every content fragment, front matter blanked."""
    for path, text in ctx.sources.items():
        body = re.sub(r"\A\s*<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        root, _errors = dom.parse(body)
        yield path, root


def _code_texts(root):
    """(node, text, kind): every inline <code> outside a <pre>, and every
    line of every <pre>."""
    for n in root.walk():
        if n.tag == "code" and not _inside(n, "pre"):
            yield n, n.text(), "inline"
        elif n.tag == "pre":
            for i, line in enumerate(n.text().split("\n")):
                yield n, line, f"block:{n.get('data-lang', '')}"


def _inside(n, tag) -> bool:
    p = n.parent
    while p is not None:
        if getattr(p, "tag", None) == tag:
            return True
        p = p.parent
    return False


# ---------------------------------------------------------------------------
# rmp, cmake
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def rmp_help(framework: str) -> dict:
    got = subprocess.run([sys.executable, str(Path(framework) / "tools" / "rmp.py"), "help", "--json"],
                         capture_output=True, text=True, cwd=framework)
    if got.returncode != 0:
        raise RuntimeError(f"rmp help --json failed: {got.stderr.strip()}")
    return json.loads(got.stdout)


def rmp_problem(words: list[str], help_data: dict, examples: set[str]) -> str | None:
    commands = {c["name"]: c for c in help_data["commands"]}
    stages = {s["name"] for s in help_data["stages"]}
    words = [w.rstrip("\\") for w in words]
    if not words:
        return None
    command, rest = words[0], words[1:]
    if command in ("-h", "--help"):
        return None
    if command not in commands:
        return f"there is no `rmp {command}`"
    usage = commands[command]["usage"].split()[1:]
    if not rest:
        return None
    arg = rest[0]
    if arg.startswith(("<", "[")) or arg.isupper():
        return None
    if not usage:
        return f"`rmp {command}` takes no argument"
    slot = usage[0].strip("[]")
    if slot == "stage":
        ok = arg in stages
    elif slot == "name":
        ok = (arg in examples or arg.removeprefix("examples/") in examples
              or any(e.endswith("/" + arg) for e in examples))
    elif slot == "command":
        ok = arg in commands or arg == "--json"
    elif slot.isupper():
        ok = True
    else:
        ok = arg == slot or (command == "new" and arg == "--list")
    return None if ok else f"`rmp {command}` does not take {arg!r}"


def _examples(fw: Path) -> set[str]:
    root = fw / "examples"
    found = set()
    for main in list(root.glob("**/src/main.cpp")) + list(root.glob("**/src/main.c")):
        found.add(main.parent.parent.relative_to(root).as_posix())
    return found


@gate("commands", "every rmp command a page shows exists and takes the argument it is given "
                  "(read from `rmp help --json`), and every cmake --preset is a preset the "
                  "framework has")
def check_commands(ctx: Context) -> list[Problem]:
    fw = ctx.framework
    if fw is None or not (fw / "tools" / "rmp.py").is_file():
        return []
    help_data = rmp_help(str(fw))
    examples = _examples(fw)
    presets = set()
    if (fw / "CMakePresets.json").is_file():
        data = json.loads((fw / "CMakePresets.json").read_text())
        presets = {p["name"] for p in data.get("configurePresets", []) + data.get("buildPresets", [])}
    out = []
    for path, root in _fragments(ctx):
        for node, text, kind in _code_texts(root):
            line = text.strip()
            if kind.startswith("block:") and kind not in ("block:shell", "block:powershell", "block:"):
                continue
            for m in re.finditer(r"(?:^|[;&|]\s*|&&\s*)(?:\./)?rmp(?:\.ps1|\.cmd)?\s+([^;&|#`]+)", line):
                try:
                    words = shlex.split(m.group(1))
                except ValueError:
                    words = m.group(1).split()
                why = rmp_problem(words, help_data, examples)
                if why:
                    out.append(Problem("commands", path, node.line, f"rmp {m.group(1).strip()}: {why}"))
            for m in re.finditer(r"--preset[ =]([\w-]+)", line):
                if presets and m.group(1) not in presets:
                    out.append(Problem("commands", path, node.line,
                                       f"cmake --preset {m.group(1)}: the framework has "
                                       f"{', '.join(sorted(presets))}"))
    return out


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def known_names(framework: str) -> dict:
    fw = Path(framework)
    from .reference import Reference
    ref = Reference(fw, {}).read()
    rmp = {e.qualname for e in ref.entities()}
    macros = {e.name for e in ref.entities() if e.kind == "macro"}
    defines = set()
    try:
        got = subprocess.run([sys.executable, "tools/configure.py", "--print-defines"],
                             capture_output=True, text=True, cwd=fw)
        defines = {d["name"] for d in json.loads(got.stdout)}
    except Exception:  # noqa: BLE001 - a fixture framework without configure.py
        pass
    c_names = set()
    for rel in ("thirdparty/raylib/src/raylib.h", "thirdparty/raylib/src/raymath.h",
                "thirdparty/raylib/src/rlgl.h", "thirdparty/clay/clay.h"):
        p = fw / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        c_names |= set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", text))
        c_names |= set(re.findall(r"^\s*([A-Z][A-Z0-9_]+)\s*(?:=|,)", text, re.M))
        c_names |= set(re.findall(r"#define\s+(\w+)", text))
        c_names |= set(re.findall(r"typedef\s+(?:struct|enum)\s+\w*\s*\{[^}]*\}\s*(\w+)", text, re.S))
        c_names |= set(re.findall(r"\}\s*(\w+)\s*;", text))
    return {"rmp": rmp, "macros": macros | defines, "c": c_names}


@gate("names", "every name a page writes in code that looks like the framework's or raylib's "
               "-- rmp::..., RMP_..., a raylib, rlgl or Clay function or constant -- is one the "
               "headers at FRAMEWORK_REF declare")
def check_names(ctx: Context) -> list[Problem]:
    fw = ctx.framework
    if fw is None or not (fw / "include" / "rmp").is_dir():
        return []
    names = known_names(str(fw))
    rmp_names = names["rmp"] | {q.rsplit("::", 1)[0] for q in names["rmp"]}
    out = []
    for path, root in _fragments(ctx):
        for node, text, kind in _code_texts(root):
            if kind != "inline":
                continue
            t = text.strip()
            for m in re.finditer(r"\brmp::[A-Za-z_][\w:]*", t):
                q = re.sub(r"::$", "", m.group(0))
                if q not in rmp_names and q not in ("rmp",):
                    out.append(Problem("names", path, node.line, f"`{q}` names nothing in include/rmp/"))
            for m in re.finditer(r"\bRMP_[A-Z0-9_]+\b", t):
                if m.group(0) not in names["macros"] and m.group(0) not in ctx.refconf.get("build_defines", {}):
                    out.append(Problem("names", path, node.line,
                                       f"`{m.group(0)}` is not a macro of the framework or a value the .toml sets"))
            # A raylib/rlgl/Clay-shaped call: CamelCase( or Clay_x( -- must exist.
            m = re.fullmatch(r"((?:Clay_|rl)?[A-Z][A-Za-z0-9_]*)\(.*\)", t)
            if m and names["c"] and m.group(1) not in names["c"] and not m.group(1)[0].islower():
                out.append(Problem("names", path, node.line,
                                   f"`{m.group(1)}()` is not a function raylib, raymath, rlgl or Clay declares"))
            # KEY_SPACE, GAMEPAD_BUTTON_..., FLAG_..., MOUSE_...
            for mm in re.finditer(r"\b(KEY|GAMEPAD|MOUSE|FLAG|LOG|BLEND|TEXTURE|PIXELFORMAT)_[A-Z0-9_]+\b", t):
                if names["c"] and mm.group(0) not in names["c"]:
                    out.append(Problem("names", path, node.line, f"`{mm.group(0)}` is not a raylib constant"))
    return out


# ---------------------------------------------------------------------------
# paths and claims
# ---------------------------------------------------------------------------

PATH_SHAPED = re.compile(r"^(?:\./)?((?:src|include|tools|tests|examples|cmake|thirdparty|raymob|ios|"
                         r"resources|branding|build)/[\w./*-]*|[\w-]+\.(?:toml|cpp|h|c|py|sh|md|json|yml))/?$")


@functools.lru_cache(maxsize=4)
def game_paths(framework: str) -> frozenset:
    got = subprocess.run([sys.executable, "tools/rmp.py", "new", "--list"], capture_output=True,
                         text=True, cwd=framework)
    return frozenset(got.stdout.split()) if got.returncode == 0 else frozenset()


@gate("paths", "every path a page names in code -- src/main.cpp, examples/games/01_pong, "
               "tools/configure.py -- is a file or folder of the framework at FRAMEWORK_REF "
               "or of a game rmp new makes; every fw: link points at a file that exists, "
               "and at lines it has")
def check_paths(ctx: Context) -> list[Problem]:
    fw = ctx.framework
    if fw is None:
        return []
    game = set(game_paths(str(fw)))
    # A tutorial's game grows past what rmp new makes: the files its pages
    # write (data-project + data-file) are paths of a game too.
    for _path, root in _fragments(ctx):
        for n in root.walk():
            if n.tag == "pre" and n.get("data-project") and n.get("data-file"):
                game.add(n.get("data-file").strip("/"))
    out = []
    for path, root in _fragments(ctx):
        for node, text, kind in _code_texts(root):
            if kind != "inline":
                continue
            m = PATH_SHAPED.match(text.strip())
            if not m:
                continue
            rel = m.group(1).rstrip("/")
            if rel.startswith("build/") or rel == "build":
                continue    # made by a build, not in any checkout
            if "*" in rel:
                if not list(fw.glob(rel)):
                    out.append(Problem("paths", path, node.line, f"`{rel}` matches nothing in the framework"))
                continue
            in_game = rel in game or any(g.startswith(rel + "/") for g in game)
            if not (fw / rel).exists() and not in_game and "/" in rel:
                out.append(Problem("paths", path, node.line, f"`{rel}` is not in the framework or in a new game"))
        for n in root.walk():
            href = n.attrs.get("href", "")
            if n.tag == "a" and href.startswith("fw:"):
                target, _, frag = href[3:].partition("#")
                f = fw / target
                if not f.exists():
                    out.append(Problem("paths", path, n.line, f"{href}: no such file in the framework"))
                    continue
                lm = re.fullmatch(r"L(\d+)(?:-L(\d+))?", frag) if frag else None
                if frag and not lm:
                    out.append(Problem("paths", path, n.line, f"{href}: a line anchor is L12 or L12-L20"))
                elif lm and f.is_file():
                    count = f.read_text(encoding="utf-8", errors="replace").count("\n") + 1
                    last = int(lm.group(2) or lm.group(1))
                    if last > count or int(lm.group(1)) < 1:
                        out.append(Problem("paths", path, n.line, f"{href}: {target} has {count} lines"))
    return out


@gate("claims", "a sentence pinned to the source with data-fw-grep=\"path::regex\" still holds: "
                "the regex matches in that file at FRAMEWORK_REF")
def check_claims(ctx: Context) -> list[Problem]:
    fw = ctx.framework
    if fw is None:
        return []
    out = []
    for path, root in _fragments(ctx):
        for n in root.walk():
            spec = n.attrs.get("data-fw-grep")
            if spec is None:
                continue
            target, sep, rx = spec.partition("::")
            if not sep or not rx:
                out.append(Problem("claims", path, n.line, f"data-fw-grep={spec!r}: write path::regex"))
                continue
            f = fw / target
            if not f.is_file():
                out.append(Problem("claims", path, n.line, f"{target} does not exist"))
                continue
            try:
                found = re.search(rx, f.read_text(encoding="utf-8", errors="replace"), re.M)
            except re.error as e:
                out.append(Problem("claims", path, n.line, f"data-fw-grep regex: {e}"))
                continue
            if not found:
                out.append(Problem("claims", path, n.line,
                                   f"the claim no longer holds: /{rx}/ is not in {target}"))
    return out


@gate("pictures", "no page carries a raster image of its own: a screenshot goes stale the day "
                  "the UI changes; pictures are SVG diagrams or come from the examples job")
def check_pictures(ctx: Context) -> list[Problem]:
    out = []
    for path, root in _fragments(ctx):
        for n in root.walk():
            src = n.attrs.get("src", "") if n.tag in ("img", "source") else ""
            if re.search(r"\.(png|jpe?g|gif|webp|avif|bmp)(\?|$)", src, re.I):
                out.append(Problem("pictures", path, n.line, f"{src}: a raster image in a page"))
    content = ctx.docs / "content"
    if content.is_dir():
        for p in content.rglob("*"):
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"):
                out.append(Problem("pictures", f"content/{p.relative_to(content).as_posix()}", 0,
                                   "a raster image in content/"))
    return out


# ---------------------------------------------------------------------------
# quoted diagnostics
# ---------------------------------------------------------------------------

C_LITERAL = re.compile(r'"((?:\\.|[^"\\\n])*)"')
PY_LITERAL = re.compile(r'(?:f|rf|fr)?"((?:\\.|[^"\\\n])*)"|(?:f|rf|fr)?\'((?:\\.|[^\'\\\n])*)\'')
JS_LITERAL = re.compile(r'"((?:\\.|[^"\\\n])*)"|\'((?:\\.|[^\'\\\n])*)\'|`((?:\\.|[^`\\])*)`')
C_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\", "0": ""}

PRINTF_HOLE = r"%[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|z)?[sdifuxXcgpe]"
BRACE_HOLE = r"\{[^{}]*\}"                      # Python's f-strings and str.format
CMAKE_HOLE = r"\$\{[^}]*\}"                     # ${VAR}
SHELL_HOLE = r"\$\{[^}]*\}|\$\w+|\$\([^)]*\)"   # ${x} $x $(cmd)
JS_HOLE = r"\$\{[^}]*\}"                        # `${x}`

# A message has to say something of its own: a literal whose words, holes
# taken out, are shorter than this matches whatever is put in front of it --
# `'{python}'` became `.+?` and passed every <samp> on the site.
MIN_WORDS = 8


def unescape_c(s: str) -> str:
    """C's escapes, and only those. UTF-8 in a literal stays what it is --
    decoding through unicode_escape read an em dash as three Latin-1 letters."""
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return re.sub(r"\\(.)", lambda m: C_ESCAPES.get(m.group(1), m.group(1)), s)


def unescape_py(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: C_ESCAPES.get(m.group(1), m.group(1)), s)


def _join_adjacent(text: str) -> str:
    """"a" "b", and "a" on one line and f"b" on the next, are one string to the
    compiler and to whoever reads the message."""
    text = re.sub(r'"\s*\n\s*(?:[rRfF]{1,2})?"', "", text)
    text = re.sub(r"'\s*\n\s*(?:[rRfF]{1,2})?'", "", text)
    return re.sub(r'"[ \t]+"', "", text)


@functools.lru_cache(maxsize=4)
def message_patterns(framework: str) -> tuple:
    """Every message the framework can print, as its literal parts -- with a
    hole between each two: the string literals of src/rmp/, include/rmp/ and
    tests/smoke_test.h (C, printf holes), of tools/rmp.py and
    tools/configure.py ({...}), of CMakeLists.txt and cmake/ (${...}), of the
    shell scripts ($x), and of the JavaScript in cmake/web/ and
    .github/scripts/ (`${x}`). Whitespace collapsed, as a page shows it."""
    fw = Path(framework)
    messages = []

    def add(text: str, holes: str):
        parts = tuple(re.sub(r"\s+", " ", part) for part in re.split(holes, text))
        if len("".join(parts).strip()) >= MIN_WORDS:
            messages.append(parts)

    def files(*globs):
        for g in globs:
            yield from sorted(f for f in fw.glob(g) if f.is_file())

    def read(f):
        return f.read_text(encoding="utf-8", errors="replace")

    for f in files("src/rmp/**/*.cpp", "src/rmp/**/*.h", "src/rmp/**/*.c", "include/rmp/**/*.h",
                   "tests/smoke_test.h"):
        for m in C_LITERAL.finditer(_join_adjacent(read(f))):
            add(unescape_c(m.group(1)), PRINTF_HOLE)
    for f in files("tools/rmp.py", "tools/configure.py"):
        for m in PY_LITERAL.finditer(_join_adjacent(read(f))):
            add(unescape_py(m.group(1) if m.group(1) is not None else m.group(2)), BRACE_HOLE)
    for f in files("CMakeLists.txt", "cmake/**/*.cmake"):
        for m in C_LITERAL.finditer(read(f)):
            add(unescape_py(m.group(1)), CMAKE_HOLE)
    for f in files("tools/*.sh", "rmp"):
        for m in PY_LITERAL.finditer(read(f)):
            add(m.group(1) if m.group(1) is not None else m.group(2), SHELL_HOLE)
    for f in files("cmake/web/*.js", ".github/scripts/*.js"):
        for m in JS_LITERAL.finditer(read(f)):
            add(unescape_py(next(g for g in m.groups() if g is not None)), JS_HOLE)
    return tuple(messages)


def _any_suffix(s: str) -> str:
    return "(?:" + "|".join(re.escape(s[k:]) for k in range(len(s) + 1)) + ")"


def _any_prefix(s: str) -> str:
    return "(?:" + "|".join(re.escape(s[:k]) for k in range(len(s) + 1)) + ")"


def literal_in(piece: str, parts: tuple) -> int:
    """How much of `piece` is the message's own words, if `piece` is a stretch
    of some printing of it (the end of one literal part, the holes and parts
    between, the start of a later part); -1 if it is not. What a hole
    matched does not count: a stretch that is all hole says nothing."""
    if any(piece in part for part in parts):
        return len(piece)
    best = -1
    for a in range(len(parts)):
        for b in range(a + 1, len(parts)):
            middle = "".join(re.escape(part) + "(.+?)" for part in parts[a + 1:b])
            rx = _any_suffix(parts[a]) + "(.+?)" + middle + _any_prefix(parts[b])
            m = re.fullmatch(rx, piece, re.S)
            if m:
                best = max(best, len(piece) - sum(len(g) for g in m.groups()))
    return best


@gate("diagnostics", "every message a page quotes in <samp> is one the framework prints: all "
                     "its pieces are stretches of ONE string literal of the framework's C++, "
                     "tools, CMake or web scripts, the format's holes filled by anything")
def check_diagnostics(ctx: Context) -> list[Problem]:
    fw = ctx.framework
    if fw is None:
        return []
    messages = message_patterns(str(fw))
    out = []
    for path, root in _fragments(ctx):
        for n in root.walk():
            if n.tag != "samp":
                continue
            said = shown = re.sub(r"\s+", " ", n.text()).strip()
            # What prints a message is not the message: raylib's log level, and
            # the word rmp and configure.py put in front of a refusal.
            said = re.sub(r"^(INFO|WARNING|ERROR|DEBUG|TRACE|FATAL): ", "", said)
            said = re.sub(r"^(FALLA|FAIL|rmp|configure|error|warning): ", "", said)
            pieces = [piece.strip() for piece in re.split(r"…|\.\.\.", said) if piece.strip()]
            if not pieces:
                continue
            longest = max(pieces, key=len)

            def holds(parts):
                # "A … B" says ONE message holds both, and together they say
                # something of its own. The longest piece first: it is the
                # one that rules most messages out.
                if literal_in(longest, parts) < 0:
                    return False
                said_of_its_own = [literal_in(x, parts) for x in pieces]
                return min(said_of_its_own) >= 0 and sum(said_of_its_own) >= MIN_WORDS

            if not any(holds(parts) for parts in messages):
                out.append(Problem("diagnostics", path, n.line,
                                   f"<samp>{shown}</samp> is not a message the framework prints"))
    return out
