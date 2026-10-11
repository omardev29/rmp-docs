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

A block shown as a mistake keeps what refused it: `said` is the compiler's,
clang-tidy's or the gate's own lines about the block -- the file called
snippet.cpp and every line number counted from the block's first line, so
the reader sees the words the tool prints and never words typed for it. The
compile tier fills it before the pages are written, and the page prints it
under the block.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

HARNESSES = Path(__file__).resolve().parents[2] / "snippets" / "harness"


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
    gate_rule: str = ""        # and the rule it has to name
    said: str = ""             # what refused it, the tool's lines about the block (compile tier)
    said_by: str = ""          # and which tool that was: "clang++", "clang-tidy", a script


# The framework's text gates a block can be run through: the script, and the
# `rmp test` stage it is, for the caption.
GATES = {"naming": (["bash", "tools/naming_check.sh"], "naming"),
         "style": (["bash", "tools/style_check.sh"], "style"),
         "ownership": (["bash", "tools/ownership_check.sh"], "ownership")}


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
    a diagnostic's line is measured from."""
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


def compile_one(s: Snippet, framework: Path, cxx: list[str]) -> tuple[bool, str]:
    source, suffix = assemble(s, framework)
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"snippet{suffix}"
        f.write_text(source, encoding="utf-8")
        argv = (c_command(cxx) if suffix == ".c" else cxx) + ["-fsyntax-only", str(f)]
        got = subprocess.run(argv, capture_output=True, text=True)
        said = (got.stdout + got.stderr).replace(str(f), "snippet" + suffix)
        return got.returncode == 0, said


# A compiler's diagnostic, as GCC and Clang both print it.
COMPILER_LINE = re.compile(r"^(snippet\.(?:cpp|c)):(\d+):(\d+): (error|warning|note): (.*)$")


def compiler_said(s: Snippet, framework: Path, output: str, most: int = 4) -> str:
    """The compiler's errors on the block's own lines, as it printed them,
    with the line counted from the block's first line. An error the block
    causes somewhere else -- inside a header it called into -- is said where
    the compiler said it, the framework's path made relative to it."""
    _source, _suffix, first = assemble_at(s, framework)
    last = first + s.code.count("\n")
    own, elsewhere = [], []
    for line in output.splitlines():
        m = COMPILER_LINE.match(line)
        if m and m.group(4) == "error" and first <= int(m.group(2)) <= last:
            own.append(f"{m.group(1)}:{int(m.group(2)) - first + 1}:{m.group(3)}: error: {m.group(5)}")
        elif ": error: " in line and not m:
            elsewhere.append(line.replace(str(framework) + "/", ""))
    return "\n".join((own or elsewhere)[:most])


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


def lint_one(s: Snippet, framework: Path, cxx: list[str], binary: str):
    """(check, line in the snippet, message) for every diagnostic clang-tidy
    gives on the snippet's own lines, with the framework's .clang-tidy. The
    harness, the given and the headers are not the block's to answer for."""
    return lint_run(s, framework, cxx, binary)[0]


def lint_run(s: Snippet, framework: Path, cxx: list[str], binary: str):
    """lint_one's findings, and clang-tidy's own lines for them: the
    diagnostic as it printed it, on snippet.cpp at the block's line."""
    source, suffix, first = assemble_at(s, framework)
    last = first + s.code.count("\n")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"snippet{suffix}"
        f.write_text(source, encoding="utf-8")
        got = subprocess.run([binary, "--quiet", *tidy_flags(binary),
                              f"--config-file={framework / '.clang-tidy'}", str(f), "--",
                              *lint_args(cxx)], capture_output=True, text=True)
        found, lines = [], []
        for m in QUERY_ERROR.finditer(got.stdout + got.stderr):
            found.append(("clang-tidy", 0, "a CustomChecks query of the framework's .clang-tidy "
                          f"did not parse, so its check never ran: {m.group(0).strip()}"))
        for line in (got.stdout + got.stderr).splitlines():
            m = DIAGNOSTIC.match(line)
            if not m or Path(m.group(1)).resolve() != f.resolve():
                continue
            at = int(m.group(2))
            if first <= at <= last:
                checks = m.group(6).split(",")
                for check in checks:
                    found.append((check, at - first + 1, m.group(5)))
                lines.append((s.expect_lint not in checks, at,
                              f"snippet{suffix}:{at - first + 1}:{m.group(3)}: {m.group(4)}: "
                              f"{m.group(5)} [{m.group(6)}]"))
        # The check the page names first, then the rest, each in line order.
        return found, [text for _other, _at, text in sorted(lines)]


def gate_one(s: Snippet, framework: Path) -> list[tuple[str, int, str]]:
    """(rule, line in the snippet, what) for every finding the gate makes on
    the snippet's own lines."""
    return gate_run(s, framework)[0]


def gate_run(s: Snippet, framework: Path):
    """gate_one's findings, and the gate's own lines for them, as the script
    printed them, on snippet.cpp at the block's line."""
    argv, _stage = GATES[s.expect_gate]
    source, suffix, first = assemble_at(s, framework)
    last = first + s.code.count("\n")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"snippet{suffix}"
        f.write_text(source, encoding="utf-8")
        got = subprocess.run([*argv, str(f)], capture_output=True, text=True, cwd=framework)
        found, lines = [], []
        for line in got.stdout.splitlines():
            m = re.match(r"^\s*FAIL\s+(.*?):(\d+): ([A-Z]\d+) (.*)$", line)
            if m and Path(m.group(1)).resolve() == f.resolve() and first <= int(m.group(2)) <= last:
                at = int(m.group(2)) - first + 1
                found.append((m.group(3), at, m.group(4)))
                lines.append((m.group(3) != s.gate_rule, at,
                              f"FAIL  snippet{suffix}:{at}: {m.group(3)} {m.group(4)}"))
        return found, [text for _other, _at, text in sorted(lines)]


def said(found) -> str:
    return "\n".join(f"  line {line}: {what} [{name}]" for name, line, what in found[:8])


def check(snippets: list[Snippet], framework: Path, jobs: int | None = None):
    """(snippet, problem or None) for every snippet, compiled in parallel."""
    cxx = compile_command(framework)
    binary = tidy()

    def one(s: Snippet):
        ok, said_by_compiler = compile_one(s, framework, cxx)
        if s.expect_error:
            s.output = said_by_compiler
            s.said = compiler_said(s, framework, said_by_compiler)
            s.said_by = Path(cxx[0]).name
            if ok:
                return s, "is shown as a mistake (data-expect=\"error\") and compiles"
            if s.error_text and s.error_text not in said_by_compiler:
                return s, f"fails, but the compiler does not say {s.error_text!r}:\n{said_by_compiler[:600]}"
            return s, None
        if not ok:
            first = "\n".join(said_by_compiler.splitlines()[:12])
            return s, f"does not compile in the {s.harness} harness:\n{first}"
        if s.expect_lint or s.lint_clean:
            if binary is None:
                return s, "is checked with clang-tidy, and there is no clang-tidy on PATH"
            cannot = custom_checks_problem(framework, binary)
            if cannot:
                return s, f"is checked with clang-tidy, and {cannot}"
            if s.expect_lint and s.expect_lint not in enabled_checks(str(framework), binary):
                return s, (f"is shown as refused by {s.expect_lint}, and the framework does not run "
                           f"{s.expect_lint}: its .clang-tidy does not enable it")
            found, lines = lint_run(s, framework, cxx, binary)
            if s.expect_lint:
                s.said, s.said_by = "\n".join(lines[:6]), "clang-tidy"
            unread = [w for name, _l, w in found if name == "clang-tidy"]
            if unread:
                return s, "is checked with clang-tidy, and " + "; ".join(unread)
            if s.expect_lint and not any(name == s.expect_lint for name, _l, _w in found):
                if not found:
                    return s, (f"is shown as refused by {s.expect_lint}, and clang-tidy says nothing "
                               "about it")
                return s, (f"is shown as refused by {s.expect_lint}, and clang-tidy does not say it; "
                           f"it says:\n{said(found)}")
            if s.lint_clean and found:
                return s, ("is shown as the right way, and clang-tidy, with the framework's "
                           f".clang-tidy, has something to say about it:\n{said(found)}")
        if s.expect_gate:
            found, lines = gate_run(s, framework)
            s.said, s.said_by = "\n".join(lines[:6]), " ".join(GATES[s.expect_gate][0][1:])
            if not any(rule == s.gate_rule for rule, _l, _w in found):
                script = " ".join(GATES[s.expect_gate][0][1:])
                return s, (f"is shown as refused by {s.gate_rule} of {script}, and it does not "
                           "report that: " + (f"it says\n{said(found)}" if found else "it says nothing"))
        return s, None

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
