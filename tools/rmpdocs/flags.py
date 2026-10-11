"""The flags gate: every flag the framework's hardening and debug checks can
give a build is written on the Security page.

The framework marks the CMake that chooses those flags with a pair of comment
lines, in CMakeLists.txt (the release hardening) and in cmake/sanitize.cmake
(the sanitizers and the debug library checks):

    # BEGIN flags documented on rmp-docs framework/security.html
    ...
    # END flags documented on rmp-docs framework/security.html

Its own SecurityPageMarkersTest holds the other half: every statement that can
emit one of those flags lies between the two lines. This gate reads every
statement between them, takes out each flag it can emit -- -f..., -W...,
-Wl,..., -D... and the defines target_compile_definitions() names, -U...,
MSVC's /... -- and fails when content/framework/security.html does not write
it as code. A flag added to the framework without its paragraph is red here;
and because the framework's `docs` job runs these gates against its own
checkout, it is red there too, on the commit that added it.

Read from the framework checkout the build was pointed at, like every gate
that reads the framework: FRAMEWORK_REF in this site's CI, the pushed commit
in the framework's.

What a flag with a variable in it asks of the page:

    -D_FORTIFY_SOURCE=${_level}     _level is set to 3 and to 2 in the block:
                                    the page writes -D_FORTIFY_SOURCE=3 and =2
    -fsanitize=${_joined}           _joined is a list(JOIN) of a list the block
                                    appends float-cast-overflow to: the page
                                    writes some -fsanitize=...,float-cast-overflow
    -fsanitize-ignorelist=${X}      X is set outside the block: the page writes
                                    -fsanitize-ignorelist=...

And the flags no literal spells: POSITION_INDEPENDENT_CODE makes CMake add
-fPIE and -pie, so a block that names RMP_RELEASE_PIE asks for both (KEYED).
Every option() a block declares is named on the page too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import dom
from .checks import Context, Problem, gate

PAGE = "content/framework/security.html"
BEGIN = "# BEGIN flags documented on rmp-docs framework/security.html"
END = "# END flags documented on rmp-docs framework/security.html"

# The files that must hold a pair. Any other CMake file of the framework that
# holds one is read as well.
REQUIRED = ("CMakeLists.txt", "cmake/sanitize.cmake")

# Flags that come from a CMake property rather than a literal, keyed on the
# name a block uses to turn the property on: check_pie_supported() and
# POSITION_INDEPENDENT_CODE give gcc and clang -fPIE to compile and -pie to link.
KEYED = {"RMP_RELEASE_PIE": ("-fPIE", "-pie")}

DEFINERS = {"target_compile_definitions", "add_compile_definitions"}


# ---------------------------------------------------------------------------
# CMake, read as statements -- the framework's tests/configure_test.py reads
# it the same way (cmake_statements, cmake_arguments, flags_of)
# ---------------------------------------------------------------------------

_COMMAND = re.compile(r"[A-Za-z_][A-Za-z0-9_]*[ \t]*\(")
_BRACKET = re.compile(r"\[(=*)\[")


def cmake_statements(text: str) -> list[tuple[int, int, str, str]]:
    """(first line, last line, command, arguments) of every command invocation
    in CMake source, in order. Comments and bracket arguments are skipped, and
    a parenthesis inside a quoted argument is text, not nesting."""
    out = []
    i, line, n = 0, 1, len(text)

    def skip_bracket(at: int, opened: re.Match) -> int:
        close = "]" + opened.group(1) + "]"
        end = text.find(close, at)
        return n if end < 0 else end + len(close)

    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "#":
            bracket = _BRACKET.match(text, i + 1)
            end = skip_bracket(i, bracket) if bracket else text.find("\n", i)
            end = n if end < 0 else end
            line += text.count("\n", i, end)
            i = end
            continue
        m = _COMMAND.match(text, i)
        if m and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
            first = line
            j, depth = m.end(), 1
            while j < n and depth:
                ch = text[j]
                if ch == '"':
                    k = j + 1
                    while k < n and text[k] != '"':
                        k += 2 if text[k] == "\\" else 1
                    line += text.count("\n", j, k)
                    j = k + 1
                    continue
                bracket = _BRACKET.match(text, j) if ch == "[" else None
                if bracket:
                    end = skip_bracket(j, bracket)
                    line += text.count("\n", j, end)
                    j = end
                    continue
                if ch == "#":
                    end = text.find("\n", j)
                    j = n if end < 0 else end
                    continue
                if ch == "\n":
                    line += 1
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                j += 1
            name = m.group(0)[:-1].strip().lower()
            out.append((first, line, name, text[m.end():j - 1]))
            i = j
            continue
        i += 1
    return out


def cmake_arguments(args: str) -> list[str]:
    """The arguments of one invocation, split as CMake splits them: on
    whitespace outside quotes, a quoted argument kept with its quotes."""
    return re.findall(r'"(?:[^"\\]|\\.)*"|[^\s"]+', args)


def unwrap(args: str) -> str:
    """Generator expressions taken off what they guard:
    $<$<COMPILE_LANGUAGE:CXX>:_GLIBCXX_ASSERTIONS> is _GLIBCXX_ASSERTIONS."""
    while True:
        unwrapped = re.sub(r"\$<(?:[^<>:]*:)?([^<>]*)>", r"\1", args)
        if unwrapped == args:
            return args
        args = unwrapped


def flags_of(name: str, args: str) -> list[str]:
    """The flags and -D defines in one statement's arguments: what a reader
    would call the flags it emits. A bracket argument is text -- the C source
    of a probe, say, where `a -b` is arithmetic -- and gives none."""
    args = re.sub(r"\[(=*)\[.*?\]\1\]", " ", args, flags=re.S)
    words = [w.strip('"') for w in cmake_arguments(unwrap(args))]
    if name in DEFINERS:
        skip = {"PRIVATE", "PUBLIC", "INTERFACE"}
        words = words[1:] if name.startswith("target_") else words
        return [w if w.startswith("-D") else "-D" + w for w in words if w and w not in skip]
    found = []
    for w in words:
        found += re.findall(r"(?<![\w$}/])(?:-[A-Za-z][^\s\"'<>;]*|/[A-Za-z][\w:=.-]*)", w)
    return found


# ---------------------------------------------------------------------------
# one file's block
# ---------------------------------------------------------------------------

@dataclass
class Want:
    """One flag a block can emit, and what the page has to write for it."""
    flag: str                   # as the block spells it: -D_FORTIFY_SOURCE=${_level}
    line: int                   # in the framework file
    prefix: str = ""            # the flag up to its first ${...}, when it has one
    values: list = field(default_factory=list)   # what that ${...} can hold, known in the block


@dataclass
class Block:
    path: str
    begin: int = 0
    end: int = 0
    wrong: list = field(default_factory=list)    # (line, message) about the markers
    wants: list = field(default_factory=list)    # Want
    options: list = field(default_factory=list)  # (line, name) of every option()


def markers(text: str) -> tuple[list[int], list[int]]:
    """The lines of every BEGIN and END marker, as whole lines."""
    lines = text.splitlines()
    begins = [i + 1 for i, l in enumerate(lines) if l.strip() == BEGIN]
    ends = [i + 1 for i, l in enumerate(lines) if l.strip() == END]
    return begins, ends


def _literal(word: str) -> str | None:
    w = word.strip('"')
    if not w or "${" in w or "$<" in w:
        return None
    return w


def _values(statements) -> dict[str, set]:
    """What each variable of the block can hold, as far as the block itself
    says: set(), list(APPEND/PREPEND/INSERT) and list(JOIN), followed to a
    fixed point. A variable set outside the block holds nothing known."""
    known: dict[str, set] = {}
    flows: list[tuple[str, str]] = []           # (from, to): to gets from's values
    for _first, _last, name, args in statements:
        words = cmake_arguments(args)
        if name == "set" and words:
            target, rest = words[0], words[1:]
            for w in rest:
                if w in ("PARENT_SCOPE", "CACHE", "FORCE"):
                    break
                lit = _literal(w)
                if lit is not None:
                    known.setdefault(target, set()).add(lit)
                elif re.fullmatch(r"\$\{(\w+)\}", w):
                    flows.append((w[2:-1], target))
        elif name == "list" and len(words) >= 3:
            op = words[0]
            if op in ("APPEND", "PREPEND", "INSERT"):
                target = words[1]
                rest = words[3:] if op == "INSERT" else words[2:]
                for w in rest:
                    lit = _literal(w)
                    if lit is not None:
                        known.setdefault(target, set()).add(lit)
                    elif re.fullmatch(r"\$\{(\w+)\}", w):
                        flows.append((w[2:-1], target))
            elif op == "JOIN" and len(words) >= 4:
                flows.append((words[1], words[3]))
    changed = True
    while changed:
        changed = False
        for source, target in flows:
            add = known.get(source, set()) - known.get(target, set())
            if add:
                known.setdefault(target, set()).update(add)
                changed = True
    return known


def read_block(path: str, text: str) -> Block:
    block = Block(path)
    begins, ends = markers(text)
    if not begins and not ends:
        block.wrong.append((0, f"has no `{BEGIN}` and no `{END}`: the gate cannot tell which "
                               "flags the Security page has to list. Put the pair back around "
                               "the CMake that chooses them"))
        return block
    if len(begins) != 1 or len(ends) != 1:
        at = (begins + ends)[0]
        block.wrong.append((at, f"has {len(begins)} BEGIN and {len(ends)} END marker(s), and the "
                                "gate reads exactly one pair"))
        return block
    block.begin, block.end = begins[0], ends[0]
    if block.end < block.begin:
        block.wrong.append((block.end, f"END (line {block.end}) comes before BEGIN (line "
                                       f"{block.begin}): the pair is out of order"))
        return block
    inside = [s for s in cmake_statements(text) if block.begin < s[0] and s[1] < block.end]
    values = _values(inside)
    seen = set()
    for first, _last, name, args in inside:
        if name == "message":
            continue
        if name == "option":
            words = cmake_arguments(args)
            if words:
                block.options.append((first, words[0]))
        for flag in flags_of(name, args):
            if flag in seen:
                continue
            seen.add(flag)
            hole = re.search(r"\$\{(\w+)\}", flag)
            if hole:
                block.wants.append(Want(flag, first, flag[:hole.start()],
                                        sorted(values.get(hole.group(1), ()))))
            else:
                block.wants.append(Want(flag, first))
        words = set(re.findall(r"[A-Za-z_]\w*", args))
        for key, keyed in KEYED.items():
            if key in words:
                for flag in keyed:
                    if flag not in seen:
                        seen.add(flag)
                        block.wants.append(Want(flag, first))
    return block


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------

def page_code(text: str) -> list[str]:
    """Every piece of code the page writes: each inline <code> and each <pre>,
    as the reader sees it (entities decoded)."""
    body = re.sub(r"\A\s*<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    root, _errors = dom.parse(body)
    out = []
    for n in root.walk():
        if n.tag == "pre" or (n.tag == "code" and not _inside(n, "pre")):
            out.append(n.text())
    return out


def _inside(n, tag) -> bool:
    p = n.parent
    while p is not None:
        if getattr(p, "tag", None) == tag:
            return True
        p = p.parent
    return False


def tokens(code: list[str]) -> set[str]:
    out = set()
    for piece in code:
        for t in re.findall(r"[^\s\"'`()<>\[\]{};|&]+", piece):
            out.add(t.rstrip(".,;:"))
    return out


def _forms(flag: str) -> tuple[str, ...]:
    """How the page may write it: a define with or without its -D."""
    return (flag, flag[2:]) if flag.startswith("-D") and len(flag) > 2 else (flag,)


def missing(want: Want, toks: set[str]) -> list[str]:
    """What the page lacks for one flag, said as the reason: [] when it
    writes all of it."""
    if not want.prefix:
        if any(f in toks for f in _forms(want.flag)):
            return []
        return [f"`{want.flag}` is a flag"]
    starts = [t for t in toks if any(t.startswith(p) for p in _forms(want.prefix))]
    if not starts:
        return [f"`{want.prefix}…` (the block's `{want.flag}`) is a flag"]
    lacking = []
    for v in want.values:
        held = False
        for t in starts:
            p = next(p for p in _forms(want.prefix) if t.startswith(p))
            if v in t[len(p):].split(","):
                held = True
                break
        if not held:
            lacking.append(f"`{want.prefix}` with `{v}` (the block's `{want.flag}` can hold it) "
                           "is a flag")
    return lacking


def _named(name: str, code: list[str]) -> bool:
    """`NAME` written as a word of its own, or given with -D: -DNAME=OFF."""
    rx = re.compile(rf"(?:(?<![A-Za-z0-9_])|(?<=-D)){re.escape(name)}(?![A-Za-z0-9_])")
    return any(rx.search(piece) for piece in code)


def framework_files(fw) -> list[str]:
    """The framework's CMake files that hold a marker, and the ones that must."""
    found = set(REQUIRED)
    for p in [fw / "CMakeLists.txt", *sorted((fw / "cmake").rglob("*.cmake"))]:
        if p.is_file() and "generated" not in p.relative_to(fw).parts:
            text = p.read_text(encoding="utf-8", errors="replace")
            if BEGIN in text or END in text:
                found.add(p.relative_to(fw).as_posix())
    return sorted(found)


@gate("flags", "every flag the framework's release hardening and debug checks can give a build "
               "-- everything between the `# BEGIN/END flags documented on rmp-docs "
               "framework/security.html` lines of CMakeLists.txt and cmake/sanitize.cmake -- is "
               "written as code on that page; and each file holds exactly one pair, in order")
def check_flags(ctx: Context) -> list[Problem]:
    fw = ctx.framework
    if fw is None or not (fw / "CMakeLists.txt").is_file():
        return []
    out = []
    blocks = []
    for rel in framework_files(fw):
        where = f"{rel} (framework)"
        f = fw / rel
        if not f.is_file():
            out.append(Problem("flags", where, 0, "is not there, and it is where the gate reads "
                                                  "the flags the Security page lists"))
            continue
        block = read_block(rel, f.read_text(encoding="utf-8", errors="replace"))
        out += [Problem("flags", where, line, msg) for line, msg in block.wrong]
        if not block.wrong:
            blocks.append(block)
    if not blocks:
        return out
    if PAGE not in ctx.sources:
        names = ", ".join(sorted({w.flag for b in blocks for w in b.wants}))
        return out + [Problem("flags", PAGE, 0, f"is not there, and the framework marks flags it "
                                                f"has to list: {names}")]
    code = page_code(ctx.sources[PAGE])
    toks = tokens(code)
    for block in blocks:
        for want in block.wants:
            for lacking in missing(want, toks):
                out.append(Problem("flags", PAGE, 0,
                                   f"{lacking} {block.path} can give a build (line {want.line}, "
                                   "between its markers), and the page never writes it as code: "
                                   "say what it protects against and what it costs"))
        for line, name in block.options:
            if not _named(name, code):
                out.append(Problem("flags", PAGE, 0,
                                   f"`{name}` is an option {block.path} declares between its "
                                   f"markers (line {line}), and the page never names it as code"))
    return out
