"""Every C and C++ block a page shows is compiled against the framework.

A block says how, with one attribute:

    data-include="examples/.../main.cpp"   quoted from a real source, which the
                                           framework's CI builds and boots
    data-harness="function"                compiled inside snippets/harness/<name>
    data-harness="..." data-expect="error" data-error="text"
                                           a mistake on purpose: it must FAIL,
                                           and the compiler must say `text`

and optionally data-given="..." -- declarations the snippet uses and does not
show (`void play();`), compiled in front of it.

The harnesses are files under snippets/harness/; each says, in its first
comment, where the snippet lands. The flags are the framework's own: the
compile command its build gives an example, from build/lint's
compile_commands.json, with -fsyntax-only. A block with none of the three is
a problem: code nobody compiled is code that may not compile.

A rule of style is shown wrong as well as right, and the wrong way usually
compiles. Two more expectations say what refuses it instead:

    data-expect="lint" data-check="modernize-avoid-c-style-cast"
                                           it compiles, the framework's
                                           .clang-tidy enables that check, and
                                           the check fires on a line of the block
    data-expect="gate" data-gate="naming" data-rule="R2"
                                           it compiles, and the framework's
                                           tools/naming_check.sh reports that
                                           rule on a line of the block

and every other C++ block of content/guidelines/ -- the right way -- has to
pass clang-tidy with the framework's .clang-tidy and say nothing (lint_clean):
a page that teaches a rule cannot show code the rule's own tool refuses.

clang-tidy here is the framework's own lint, and the framework's .clang-tidy
has CustomChecks: queries that clang-tidy registers only with
--experimental-custom-checks, and leaves out in silence without it -- as it
does a query that does not parse, with one "Error parsing" line and exit 0.
So a clang-tidy without the flag cannot hold a block to that file, and a
query it could not read is a problem, not a quiet pass.

And every block that is not shown as a mistake -- every page's, and every
file a tutorial writes -- passes the framework's tools/style_check.sh: the
style rules clang-tidy cannot see (`++i`, no C cast, no NULL), which the
framework's examples are held to as well (style).

Two more gates take a block that compiles, and neither names a rule:

    data-expect="gate" data-gate="pointers"   tools/pointer_check.py reads the
                                           block as a public header -- the
                                           `header` harness -- and refuses a
                                           pointer or a C string a game can name
    data-expect="gate" data-gate="format"     clang-format, with the framework's
                                           .clang-format, would change it

and the right way on a Guidelines page is held to clang-format too
(format_clean): a page about how the code reads shows code formatted the way
the framework's is.

WHAT THE TOOL SAID. A block shown refused carries the tool's own words --
the compiler's error, clang-tidy's warning, the gate's FAIL line -- as the tool
printed them about the block's own lines, with the file called snippet.cpp (or
rmp/snippet.h) and every line number the block's own (shown()). Never typed:
the page has a slot for them, and the build fills it once the compile tier has
run the tool (Site.show_said).
"""

from __future__ import annotations

import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

HARNESSES = Path(__file__).resolve().parents[2] / "snippets" / "harness"

# The harness whose block is a header of its own, include/rmp/snippet.h, and
# not lines spliced into the harness file.
HEADER = "header"


@dataclass
class Snippet:
    page: str          # the page's source, content/...
    line: int
    lang: str          # cpp or c
    code: str
    harness: str
    given: str = ""
    expect_error: bool = False
    error_text: str = ""
    output: str = ""   # what the compiler said, for an expect-error block
    expect_lint: str = ""      # the clang-tidy check that has to fire on it
    lint_clean: bool = False   # clang-tidy has to say nothing about it
    expect_gate: str = ""      # a gate of the framework's (GATES) that has to refuse it
    gate_rule: str = ""        # and the rule it has to name, for a gate that has rules
    format_clean: bool = False  # clang-format has to leave it as it is
    gates_clean: bool = False  # the text gates (CLEAN_GATES) have to say nothing about it
    said: str = ""     # what refused it, as the page shows it (shown())


class Gate(tuple):
    """A gate of the framework's a block can be shown refused by: how it is
    run, the `rmp test` stage it is (for the caption), and whether its
    findings name a rule (R2, S6, O1) that the page has to name too."""

    def __new__(cls, argv: list[str], stage: str, rules: bool):
        return super().__new__(cls, (argv, stage, rules))

    @property
    def argv(self) -> list[str]:
        return self[0]

    @property
    def stage(self) -> str:
        return self[1]

    @property
    def rules(self) -> bool:
        return self[2]


# The framework's gates a block can be run through. The text gates take the
# file; `pointers` reads the block as the public header it is (the header
# harness), and `format` is clang-format with the framework's .clang-format,
# which is what `rmp test fmt` runs over every file.
GATES = {"naming": Gate(["bash", "tools/naming_check.sh"], "naming", True),
         "style": Gate(["bash", "tools/style_check.sh"], "style", True),
         "ownership": Gate(["bash", "tools/ownership_check.sh"], "ownership", True),
         "pointers": Gate(["python3", "tools/pointer_check.py"], "pointers", False),
         "format": Gate(["clang-format"], "fmt", False)}


# The gates the right way on a Guidelines page is held to, besides clang-tidy,
# clang-format and the style gate every block passes: what clang-tidy cannot
# see -- a name in every #if branch, `other._x`, a constant named like a macro,
# a raylib Load* outside its owner -- and, for a block that is a public header,
# a pointer a game could name. A page that shows a rule cannot show, as the
# right way, code another of the framework's gates refuses.
CLEAN_GATES = ("naming", "ownership")


def harness_names() -> list[str]:
    return sorted(p.stem for p in HARNESSES.iterdir() if p.suffix in (".cpp", ".c"))


def harness_file(name: str) -> Path | None:
    for ext in (".cpp", ".c"):
        p = HARNESSES / f"{name}{ext}"
        if p.is_file():
            return p
    return None


def assemble(s: Snippet, framework: Path) -> tuple[str, str]:
    """The source to compile and its suffix."""
    out, suffix, _first = assemble_at(s, framework)
    return out, suffix


def assemble_at(s: Snippet, framework: Path) -> tuple[str, str, int]:
    """The source, its suffix, and the line of it the snippet starts on: what
    a diagnostic's line is measured from. The header harness has no place
    for the snippet: the block is a file of its own (materialise)."""
    path = harness_file(s.harness)
    template = path.read_text(encoding="utf-8")
    includes = "\n".join(f"#include <rmp/{h.name}>"
                         for h in sorted((framework / "include" / "rmp").glob("*.h")))
    out = (template.replace("// {{includes}}", includes)
                   .replace("// {{given}}", s.given).replace("/* {{given}} */", s.given))
    marks = [m for m in ("// {{snippet}}", "/* {{snippet}} */") if m in out]
    first = out.count("\n", 0, out.index(marks[0])) + 1 if marks else 1
    out = out.replace("// {{snippet}}", s.code).replace("/* {{snippet}} */", s.code)
    return out, path.suffix, first


@dataclass
class Unit:
    """A block written out to be checked: the file the compiler and
    clang-tidy are given, the file the block's own lines are in -- the same
    one, but for a header -- where in it they are, what the reader calls that
    file, and the flags that find it."""
    unit: Path
    block: Path
    first: int
    last: int
    name: str
    args: list


def materialise(s: Snippet, framework: Path, tmp: Path) -> Unit:
    source, suffix, first = assemble_at(s, framework)
    unit = tmp / f"snippet{suffix}"
    unit.write_text(source, encoding="utf-8")
    if s.harness == HEADER:
        header = tmp / "include" / "rmp" / "snippet.h"
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text(s.code + "\n", encoding="utf-8")
        return Unit(unit, header, 1, 1 + s.code.count("\n"), "include/rmp/snippet.h",
                    [f"-I{tmp / 'include'}"])
    return Unit(unit, unit, first, first + s.code.count("\n"), f"snippet{suffix}", [])


def compile_command(framework: Path) -> list[str]:
    """The framework's compile command for an example, without its output and
    input: the include path, the defines and the standard its build uses."""
    db = framework / "build" / "lint" / "compile_commands.json"
    if not db.is_file():
        raise FileNotFoundError(
            f"{db} is missing: configure the framework first --\n"
            f"  (cd {framework} && python3 tools/configure.py && cmake --preset lint)")
    entries = json.loads(db.read_text(encoding="utf-8"))
    entry = next(e for e in entries if "/examples/games/01_pong/src/main.cpp" in e["file"].replace("\\", "/"))
    argv = entry.get("arguments") or shlex.split(entry["command"])
    keep = []
    skip = False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in ("-o", "-c"):
            skip = True
            continue
        if a.endswith(".cpp") and Path(a).name == "main.cpp":
            continue
        keep.append(a)
    return keep


def c_command(cxx: list[str]) -> list[str]:
    """The same include path and defines for a C file, with a C compiler."""
    compiler = cxx[0]
    cc = re.sub(r"(clang)\+\+$", r"\1", compiler)
    cc = re.sub(r"g\+\+$", "gcc", cc)
    cc = re.sub(r"c\+\+$", "cc", cc)
    rest = [a for a in cxx[1:] if not a.startswith("-std=")]
    return [cc, "-std=c99", *rest]


def compile_unit(u: Unit, cxx: list[str]) -> tuple[bool, str]:
    """Compiled, and everything the compiler said, as it said it."""
    argv = (c_command(cxx) if u.unit.suffix == ".c" else cxx) + [*u.args, "-fsyntax-only", str(u.unit)]
    got = subprocess.run(argv, capture_output=True, text=True)
    return got.returncode == 0, got.stdout + got.stderr


def compile_one(s: Snippet, framework: Path, cxx: list[str]) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        u = materialise(s, framework, Path(tmp))
        ok, said_by_compiler = compile_unit(u, cxx)
        return ok, said_by_compiler.replace(str(u.block), u.name).replace(str(u.unit), u.unit.name)


# --- what a tool said, as the page shows it ----------------------------------------

# A diagnostic's first line, the compiler's and clang-tidy's and clang-format's
# alike; the lines after it that start with a space are its source line, its
# caret and its fix.
HEAD = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): "
                  r"(?P<kind>warning|error|fatal error|note): (?P<what>.*)$")
# `   62 |     int total = a + b;` -- the number is the file's line -- and the
# lines under it, `      |     ^`.
EXCERPT = re.compile(r"^(\s*)(\d+)( \|.*)$")
CARET = re.compile(r"^\s+\|")
# What is not part of any diagnostic: where a header was included from, the
# counts at the end, gcc's "In function ...:".
JUNK = re.compile(r"^(In file included from |\s+from |\d+ (warnings?|errors?)( and \d+ errors?)? "
                  r"generated|Suppressed \d+ warnings|Use -header-filter|Error while processing"
                  r"|.*: (In |At global scope))")
SHOWN_DIAGNOSTICS = 6


def _same(a: str, b: Path) -> bool:
    try:
        return Path(a).resolve() == b.resolve()
    except OSError:
        return False


def shown(output: str, u: Unit, keep: str = "", framework: Path | None = None) -> str:
    """What a tool printed about the block's own lines: each diagnostic on them
    with the source line and caret it printed under it, in the order it
    printed them, the file called what the reader calls it and every line
    number the block's own. A diagnostic in a header is not about the block,
    and is left out -- unless the words the page says the tool says (`keep`)
    are only there, when the first one that says them is shown too, where the
    tool printed it, its path the framework's or, for the standard library's,
    the part after `include/`. A note clang repeats is shown once."""
    groups, cur = [], None
    for raw in output.splitlines():
        m = HEAD.match(raw)
        if m:
            cur = (m, [raw])
            groups.append(cur)
        elif JUNK.match(raw) or not raw.strip():
            cur = None
        elif cur is not None:
            cur[1].append(raw.rstrip())

    def ours(m) -> bool:
        return _same(m.group("path"), u.block) and u.first <= int(m.group("line")) <= u.last

    def as_ours(m, lines) -> list[str]:
        at = int(m.group("line")) - u.first + 1
        out = [f"{u.name}:{at}:{m.group('col')}: {m.group('kind')}: {m.group('what')}"]
        outside = False   # a source line of the harness's, and its caret under it
        for line in lines[1:]:
            e = EXCERPT.match(line)
            if e:
                outside = not u.first <= int(e.group(2)) <= u.last
                width = len(e.group(1)) + len(e.group(2))
                line = str(int(e.group(2)) - u.first + 1).rjust(width) + e.group(3)
            elif not CARET.match(line):
                outside = False
            if not outside:
                out.append(line)
        return out

    def as_theirs(m, lines) -> list[str]:
        path = m.group("path")
        if _same(path, u.unit):
            path = u.unit.name
        else:
            try:
                path = Path(path).resolve().relative_to(framework.resolve()).as_posix()
            except (ValueError, AttributeError):
                # The standard library's, wherever this machine keeps it.
                if "/include/" in path:
                    path = path.rsplit("/include/", 1)[1]
        return [f"{path}:{m.group('line')}:{m.group('col')}: {m.group('kind')}: {m.group('what')}",
                *lines[1:]]

    # The block's own diagnostics, in the order the tool printed them -- and
    # when none of them says the words the page names, the first one that
    # does, where the tool printed it: an error in a header comes before the
    # notes that lead back to the block.
    said_it = [keep in "\n".join(lines) for m, lines in groups] if keep else []
    extra = None
    if keep and not any(k for k, (m, _l) in zip(said_it, groups) if ours(m)):
        extra = next((i for i, k in enumerate(said_it) if k), None)
    shown_groups, seen = [], set()
    for i, (m, lines) in enumerate(groups):
        if ours(m) or i == extra:
            g = "\n".join(as_ours(m, lines) if ours(m) else as_theirs(m, lines))
            if g not in seen:      # clang repeats an instantiation's note per error
                seen.add(g)
                shown_groups.append(g)
    text = "\n".join(shown_groups[:SHOWN_DIAGNOSTICS])
    if len(shown_groups) > SHOWN_DIAGNOSTICS:
        text += "\n\u2026"

    # A place named inside a message -- `(unnamed struct at /tmp/x/snippet.cpp:17:11)`
    # -- is the block's too.
    def place(m) -> str:
        line = int(m.group(1))
        if u.first <= line <= u.last:
            return f"{u.name}:{line - u.first + 1}"
        return f"{u.unit.name}:{line}"

    for path in sorted({str(u.block), str(u.block.resolve()), str(u.unit), str(u.unit.resolve())},
                       key=len, reverse=True):
        text = re.sub(re.escape(path) + r":(\d+)", place, text).replace(path, u.name)
    return text.strip("\n")


# --- clang-tidy -----------------------------------------------------------------

DIAGNOSTIC = re.compile(r"^(.*?):(\d+):(\d+): (warning|error): (.*?) \[([\w.,-]+)\]$")


def tidy() -> str | None:
    return shutil.which("clang-tidy")


@functools.lru_cache(maxsize=4)
def tidy_supports_custom(binary: str) -> bool:
    got = subprocess.run([binary, "--help"], capture_output=True, text=True)
    return "--experimental-custom-checks" in got.stdout


def has_custom_checks(framework: Path) -> bool:
    """Whether the framework's .clang-tidy declares CustomChecks."""
    f = framework / ".clang-tidy"
    return f.is_file() and re.search(r"^CustomChecks:", f.read_text(encoding="utf-8"), re.M) is not None


def tidy_flags(binary: str) -> list[str]:
    """--experimental-custom-checks, always where the clang-tidy has it: the
    framework's query-based checks are only run with it. A clang-tidy
    without it is refused before it is used (custom_checks_problem)."""
    return ["--experimental-custom-checks"] if tidy_supports_custom(binary) else []


def custom_checks_problem(framework: Path, binary: str) -> str | None:
    """Why this clang-tidy cannot hold a block to the framework's
    .clang-tidy, or None. Without --experimental-custom-checks it would read
    the file, run every other check and leave the CustomChecks out without a
    word, so a raw pointer would pass as the right way."""
    if has_custom_checks(framework) and not tidy_supports_custom(binary):
        return (f"the framework's .clang-tidy has CustomChecks, and {binary} has no "
                "--experimental-custom-checks to run them: use the clang-tidy "
                "thirdparty/FROZEN_VERSIONS.md pins")
    return None


# A CustomChecks query clang-tidy could not read: one line, exit 0, and the
# check never runs.
QUERY_ERROR = re.compile(r"^.*Error parsing .*$", re.M)


@functools.lru_cache(maxsize=4)
def enabled_checks(framework: str, binary: str) -> frozenset:
    """The checks the framework's .clang-tidy enables, as clang-tidy reads it."""
    got = subprocess.run([binary, "--list-checks", *tidy_flags(binary),
                          f"--config-file={Path(framework) / '.clang-tidy'}"],
                         capture_output=True, text=True)
    return frozenset(line.strip() for line in got.stdout.splitlines()
                     if line.startswith("    ") and line.strip())


def lint_args(cxx: list[str]) -> list[str]:
    """The compile command's defines, include paths and standard, and nothing
    else: the compiler's own flags are not clang's to read."""
    keep, it = [], iter(cxx[1:])
    for a in it:
        if a.startswith(("-D", "-I", "-std=")):
            keep.append(a)
        elif a in ("-isystem", "-include"):
            keep += [a, next(it, "")]
    return keep


def lint_unit(u: Unit, framework: Path, cxx: list[str], binary: str):
    """(found, what clang-tidy printed): (check, line in the block, message)
    for every diagnostic it gives on the block's own lines, with the
    framework's .clang-tidy. The harness, the given and the headers are not
    the block's to answer for."""
    got = subprocess.run([binary, "--quiet", *tidy_flags(binary),
                          f"--config-file={framework / '.clang-tidy'}", str(u.unit), "--",
                          *lint_args(cxx), *u.args], capture_output=True, text=True)
    out = got.stdout + got.stderr
    found = []
    for m in QUERY_ERROR.finditer(out):
        found.append(("clang-tidy", 0, "a CustomChecks query of the framework's .clang-tidy "
                      f"did not parse, so its check never ran: {m.group(0).strip()}"))
    for line in out.splitlines():
        m = DIAGNOSTIC.match(line)
        if not m or not _same(m.group(1), u.block):
            continue
        at = int(m.group(2))
        if u.first <= at <= u.last:
            for check in m.group(6).split(","):
                found.append((check, at - u.first + 1, m.group(5)))
    return found, out


def lint_one(s: Snippet, framework: Path, cxx: list[str], binary: str):
    """(check, line in the snippet, message) for every diagnostic clang-tidy
    gives on the snippet's own lines."""
    with tempfile.TemporaryDirectory() as tmp:
        return lint_unit(materialise(s, framework, Path(tmp)), framework, cxx, binary)[0]


# --- the framework's gates --------------------------------------------------------

FAIL_LINE = re.compile(r"^\s*FAIL:?\s+(.*?):(\d+): (.*)$")
RULE = re.compile(r"^([A-Z]\d+) (.*)$")


def _fail_lines(out: str, u: Unit, rules: bool):
    """(rule, line in the block, what, the line as the reader sees it) for
    every FAIL line a gate printed about the block's own lines."""
    found = []
    for line in out.splitlines():
        m = FAIL_LINE.match(line)
        if not m or not _same(m.group(1), u.block):
            continue
        at = int(m.group(2))
        if not u.first <= at <= u.last:
            continue
        rule, what = "", m.group(3)
        if rules:
            r = RULE.match(what)
            if not r:
                continue
            rule, what = r.group(1), r.group(2)
        shown_line = line.replace(m.group(1), u.name, 1).replace(f"{u.name}:{at}:", f"{u.name}:{at - u.first + 1}:", 1)
        found.append((rule, at - u.first + 1, what, shown_line.strip()))
    return found


def frozen_version(framework: Path, key: str) -> str | None:
    """A version thirdparty/FROZEN_VERSIONS.md pins: `clang_format 22.1.8`."""
    f = framework / "thirdparty" / "FROZEN_VERSIONS.md"
    m = re.search(rf"^{re.escape(key)}\s+(\S+)\s*$", f.read_text(encoding="utf-8"), re.M) if f.is_file() else None
    return m.group(1) if m else None


@functools.lru_cache(maxsize=4)
def _version_of(binary: str) -> str:
    return subprocess.run([binary, "--version"], capture_output=True, text=True).stdout


def format_problem(framework: Path) -> str | None:
    """Why the clang-format on PATH cannot judge a block, or None. One minor
    version out reformats code that was already right, which is why the
    framework pins it."""
    binary = shutil.which("clang-format")
    if binary is None:
        return "there is no clang-format on PATH"
    pinned = frozen_version(framework, "clang_format")
    if pinned and not re.search(rf"version {re.escape(pinned)}\b", _version_of(binary)):
        return (f"{binary} is not clang-format {pinned}, the version thirdparty/FROZEN_VERSIONS.md "
                "pins, and another would reformat code that is already right")
    return None


def format_unit(u: Unit, framework: Path, code: str):
    """(found, what clang-format printed): where clang-format, with the
    framework's .clang-format, would change the block -- read as the file it
    is, with no harness around it, which is how `rmp test fmt` reads one."""
    f = u.unit.parent / ("fmt-" + Path(u.name).name)
    f.write_text(code + "\n", encoding="utf-8")
    got = subprocess.run(["clang-format", f"--style=file:{framework / '.clang-format'}",
                          "--dry-run", str(f)], capture_output=True, text=True)
    out = got.stdout + got.stderr
    as_file = Unit(f, f, 1, 1 + code.count("\n"), u.name, [])
    found = [("", int(m.group("line")), m.group("what"))
             for m in map(HEAD.match, out.splitlines()) if m and _same(m.group("path"), f)]
    return found, shown(out, as_file)


def gate_unit(s: Snippet, u: Unit, framework: Path):
    """(found, shown, printed): (rule, line in the block, what) for every
    finding of the block's gate on the block's own lines, those findings as
    the gate printed them, and all it printed."""
    return run_gate(s.expect_gate, s, u, framework)[:3]


def run_gate(name: str, s: Snippet, u: Unit, framework: Path):
    """gate_unit, for the gate called `name`, and the gate's exit status."""
    gate = GATES[name]
    if name == "format":
        found, text = format_unit(u, framework, s.code)
        return found, text, text, 0
    if name == "pointers":
        ratchet = u.unit.parent / "no-ratchet.txt"
        ratchet.write_text("")
        # With no clang++ it would skip and exit 0, which is not a reading.
        got = subprocess.run([sys.executable, "tools/pointer_check.py", "--include",
                              str(u.block.parents[1]), "--ratchet", str(ratchet)],
                             capture_output=True, text=True, cwd=framework,
                             env={**os.environ, "RMP_REQUIRE_CLANG": "1"})
        hits = _fail_lines(got.stdout, u, rules=False)
        # Its last line says what to write instead.
        hint = [line.strip() for line in got.stdout.splitlines()
                if line.startswith("FAIL:") and not FAIL_LINE.match(line)]
        return ([(r, at, w) for r, at, w, _l in hits],
                "\n".join([l for *_x, l in hits] + (hint[-1:] if hits else [])),
                got.stdout + got.stderr, got.returncode)
    got = subprocess.run([*gate.argv, str(u.block)], capture_output=True, text=True, cwd=framework)
    hits = _fail_lines(got.stdout, u, rules=gate.rules)
    return ([(r, at, w) for r, at, w, _l in hits], "\n".join(l for *_x, l in hits),
            got.stdout + got.stderr, got.returncode)


def clean_gates(s: Snippet, u: Unit, framework: Path) -> str | None:
    """What the text gates (CLEAN_GATES) say about a block shown as the
    right way, or None when each of them ran and said nothing about its
    lines. A gate the framework does not have, or one that fails without
    naming a line -- a crash, or no clang++ for tools/pointer_check.py -- has
    not passed the block, and says so."""
    for name in [*CLEAN_GATES, *(["pointers"] if s.harness == HEADER else [])]:
        script = GATES[name].argv[-1]
        if not (framework / script).is_file():
            return f"is shown as the right way, and the framework has no {script} to hold it to"
        found, text, printed, status = run_gate(name, s, u, framework)
        if found:
            return (f"is shown as the right way, and {script} refuses it:\n"
                    + (text or said([(r or name, at, w) for r, at, w in found])))
        # A FAIL line about the harness's own lines is not the block's, and
        # not a crash either.
        if status != 0 and not any(FAIL_LINE.match(line) for line in printed.splitlines()):
            tail = "\n".join(printed.strip().splitlines()[-6:])
            return (f"is shown as the right way, and {script} failed without naming a line "
                    f"(exit {status})" + (f":\n{tail}" if tail else ""))
    return None


def gate_one(s: Snippet, framework: Path) -> list[tuple[str, int, str]]:
    """(rule, line in the snippet, what) for every finding the gate makes on
    the snippet's own lines."""
    with tempfile.TemporaryDirectory() as tmp:
        return gate_unit(s, materialise(s, framework, Path(tmp)), framework)[0]


def said(found) -> str:
    return "\n".join(f"  line {line}: {what} [{name}]" for name, line, what in found[:8])


def check(snippets: list[Snippet], framework: Path, jobs: int | None = None):
    """(snippet, problem or None) for every snippet, compiled in parallel.
    A block shown refused keeps what refused it in its `said`."""
    cxx = compile_command(framework)
    binary = tidy()

    def one(s: Snippet):
        with tempfile.TemporaryDirectory() as tmp:
            return s, judge(s, materialise(s, framework, Path(tmp)))

    def judge(s: Snippet, u: Unit) -> str | None:
        ok, out = compile_unit(u, cxx)
        if s.expect_error:
            s.output = out.replace(str(u.block), u.name).replace(str(u.unit), u.unit.name)
            if ok:
                return "is shown as a mistake (data-expect=\"error\") and compiles"
            if s.error_text and s.error_text not in out:
                return f"fails, but the compiler does not say {s.error_text!r}:\n{s.output[:600]}"
            s.said = shown(out, u, keep=s.error_text, framework=framework)
            return None if s.said else ("is shown as a mistake, and nothing the compiler said about "
                                        "its lines could be shown")
        if not ok:
            first = "\n".join(out.replace(str(u.unit), u.unit.name).splitlines()[:12])
            return f"does not compile in the {s.harness} harness:\n{first}"
        if s.expect_lint or s.lint_clean:
            if binary is None:
                return "is checked with clang-tidy, and there is no clang-tidy on PATH"
            cannot = custom_checks_problem(framework, binary)
            if cannot:
                return f"is checked with clang-tidy, and {cannot}"
            # A compiler warning, as clang-tidy reports it: --list-checks does not
            # name those, and clang-tidy says one only when the framework's
            # Checks: turn it on, so saying it is the proof.
            if (s.expect_lint and not s.expect_lint.startswith("clang-diagnostic-")
                    and s.expect_lint not in enabled_checks(str(framework), binary)):
                return (f"is shown as refused by {s.expect_lint}, and the framework does not run "
                        f"{s.expect_lint}: its .clang-tidy does not enable it")
            found, out = lint_unit(u, framework, cxx, binary)
            unread = [w for name, _l, w in found if name == "clang-tidy"]
            if unread:
                return "is checked with clang-tidy, and " + "; ".join(unread)
            if s.expect_lint and not any(name == s.expect_lint for name, _l, _w in found):
                if not found:
                    return (f"is shown as refused by {s.expect_lint}, and clang-tidy says nothing "
                            "about it")
                return (f"is shown as refused by {s.expect_lint}, and clang-tidy does not say it; "
                        f"it says:\n{said(found)}")
            if s.lint_clean and found:
                return ("is shown as the right way, and clang-tidy, with the framework's "
                        f".clang-tidy, has something to say about it:\n{said(found)}")
            if s.expect_lint:
                s.said = shown(out, u)
        if s.expect_gate == "pointers" and s.harness != HEADER:
            return ("is shown as refused by tools/pointer_check.py, which reads a public header: "
                    f"give it data-harness=\"{HEADER}\"")
        if s.expect_gate == "format" or s.format_clean:
            cannot = format_problem(framework)
            if cannot:
                return f"is checked with clang-format, and {cannot}"
        if s.expect_gate:
            gate = GATES[s.expect_gate]
            found, s.said, printed = gate_unit(s, u, framework)
            script = " ".join(gate.argv[1:]) or gate.argv[0]
            if gate.rules and not any(rule == s.gate_rule for rule, _l, _w in found):
                return (f"is shown as refused by {s.gate_rule} of {script}, and it does not "
                        "report that: " + (f"it says\n{said(found)}" if found else "it says nothing"))
            if not gate.rules and not found:
                tail = "\n".join(printed.strip().splitlines()[-6:])
                return (f"is shown as refused by {script}, and it says nothing about it"
                        + (f"; it printed:\n{tail}" if tail else ""))
        if s.format_clean:
            found, out = format_unit(u, framework, s.code)
            if found:
                return ("is shown as the right way, and clang-format, with the framework's "
                        f".clang-format, would change it:\n{out[:600]}")
        if s.gates_clean:
            problem = clean_gates(s, u, framework)
            if problem:
                return problem
        if (s.expect_error or s.expect_lint or s.expect_gate) and not s.said:
            return "is shown as refused, and nothing the tool said about its lines could be shown"
        return None

    with ThreadPoolExecutor(max_workers=jobs or max(2, (os.cpu_count() or 2) - 1)) as pool:
        return list(pool.map(one, snippets))


# --- the style rules clang-tidy cannot see ---------------------------------------

STYLE_CHECK = "tools/style_check.sh"


def style(blocks: list, framework: Path) -> list[tuple[object, int, str]]:
    """(block, line in the block, what) for every finding of the framework's
    tools/style_check.sh on the blocks: each a Snippet or a tutorial's file,
    read as the code it is -- its own lines, no harness and no given. A
    Snippet shown as a mistake is not held to it; a C file is checked as C,
    which the script exempts from the rules C cannot follow. One run of the
    script for all of them. Nothing when the framework has no such script."""
    if not (framework / STYLE_CHECK).is_file():
        return []
    held = [b for b in blocks if b.lang in ("cpp", "c")
            and not (getattr(b, "expect_error", False) or getattr(b, "expect_lint", "")
                     or getattr(b, "expect_gate", ""))]
    if not held:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        names = {}
        for i, b in enumerate(held):
            path = getattr(b, "path", "")
            suffix = Path(path).suffix if path else (".c" if b.lang == "c" else ".cpp")
            f = Path(tmp) / f"block{i:04d}{suffix}"
            f.write_text(b.code + "\n", encoding="utf-8")
            names[f.name] = b
        got = subprocess.run(["bash", STYLE_CHECK, *sorted(str(p) for p in Path(tmp).iterdir())],
                             capture_output=True, text=True, cwd=framework)
        out = []
        for line in got.stdout.splitlines():
            m = re.match(r"^\s*FAIL\s+(.*?):(\d+): ([A-Z]\d+) (.*)$", line)
            if m and Path(m.group(1)).name in names:
                out.append((names[Path(m.group(1)).name], int(m.group(2)), f"{m.group(3)} {m.group(4)}"))
        if got.returncode != 0 and not out:
            out.append((held[0], 0, f"{STYLE_CHECK} failed and named no line:\n"
                        + (got.stdout + got.stderr)[-600:]))
        return out
