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


# The framework's text gates a block can be run through: the script, and the
# `rmp test` stage it is, for the caption.
GATES = {"naming": (["bash", "tools/naming_check.sh"], "naming")}


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


# --- clang-tidy -----------------------------------------------------------------

DIAGNOSTIC = re.compile(r"^(.*?):(\d+):(\d+): (warning|error): (.*?) \[([\w.,-]+)\]$")


def tidy() -> str | None:
    return shutil.which("clang-tidy")


@functools.lru_cache(maxsize=4)
def tidy_supports_custom(binary: str) -> bool:
    got = subprocess.run([binary, "--help"], capture_output=True, text=True)
    return "--experimental-custom-checks" in got.stdout


def tidy_flags(binary: str) -> list[str]:
    """--experimental-custom-checks where the clang-tidy has it: the
    framework's query-based checks are only run with it."""
    return ["--experimental-custom-checks"] if tidy_supports_custom(binary) else []


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
    source, suffix, first = assemble_at(s, framework)
    last = first + s.code.count("\n")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"snippet{suffix}"
        f.write_text(source, encoding="utf-8")
        got = subprocess.run([binary, "--quiet", *tidy_flags(binary),
                              f"--config-file={framework / '.clang-tidy'}", str(f), "--",
                              *lint_args(cxx)], capture_output=True, text=True)
        found = []
        for line in (got.stdout + got.stderr).splitlines():
            m = DIAGNOSTIC.match(line)
            if not m or Path(m.group(1)).resolve() != f.resolve():
                continue
            at = int(m.group(2))
            if first <= at <= last:
                for check in m.group(6).split(","):
                    found.append((check, at - first + 1, m.group(5)))
        return found


def gate_one(s: Snippet, framework: Path) -> list[tuple[str, int, str]]:
    """(rule, line in the snippet, what) for every finding the gate makes on
    the snippet's own lines."""
    argv, _stage = GATES[s.expect_gate]
    source, suffix, first = assemble_at(s, framework)
    last = first + s.code.count("\n")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"snippet{suffix}"
        f.write_text(source, encoding="utf-8")
        got = subprocess.run([*argv, str(f)], capture_output=True, text=True, cwd=framework)
        found = []
        for line in got.stdout.splitlines():
            m = re.match(r"^\s*FAIL\s+(.*?):(\d+): (R\d+) (.*)$", line)
            if m and Path(m.group(1)).resolve() == f.resolve() and first <= int(m.group(2)) <= last:
                found.append((m.group(3), int(m.group(2)) - first + 1, m.group(4)))
        return found


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
            if s.expect_lint and s.expect_lint not in enabled_checks(str(framework), binary):
                return s, (f"is shown as refused by {s.expect_lint}, and the framework does not run "
                           f"{s.expect_lint}: its .clang-tidy does not enable it")
            found = lint_one(s, framework, cxx, binary)
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
            found = gate_one(s, framework)
            if not any(rule == s.gate_rule for rule, _l, _w in found):
                script = " ".join(GATES[s.expect_gate][0][1:])
                return s, (f"is shown as refused by {s.gate_rule} of {script}, and it does not "
                           "report that: " + (f"it says\n{said(found)}" if found else "it says nothing"))
        return s, None

    with ThreadPoolExecutor(max_workers=jobs or max(2, (os.cpu_count() or 2) - 1)) as pool:
        return list(pool.map(one, snippets))
