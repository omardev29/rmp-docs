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
"""

from __future__ import annotations

import json
import os
import re
import shlex
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
    path = harness_file(s.harness)
    template = path.read_text(encoding="utf-8")
    includes = "\n".join(f"#include <rmp/{h.name}>"
                         for h in sorted((framework / "include" / "rmp").glob("*.h")))
    out = (template.replace("// {{includes}}", includes)
                   .replace("// {{given}}", s.given).replace("/* {{given}} */", s.given)
                   .replace("// {{snippet}}", s.code).replace("/* {{snippet}} */", s.code))
    return out, path.suffix


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


def check(snippets: list[Snippet], framework: Path, jobs: int | None = None):
    """(snippet, problem or None) for every snippet, compiled in parallel."""
    cxx = compile_command(framework)

    def one(s: Snippet):
        ok, said = compile_one(s, framework, cxx)
        if s.expect_error:
            s.output = said
            if ok:
                return s, "is shown as a mistake (data-expect=\"error\") and compiles"
            if s.error_text and s.error_text not in said:
                return s, f"fails, but the compiler does not say {s.error_text!r}:\n{said[:600]}"
            return s, None
        if not ok:
            first = "\n".join(said.splitlines()[:12])
            return s, f"does not compile in the {s.harness} harness:\n{first}"
        return s, None

    with ThreadPoolExecutor(max_workers=jobs or max(2, (os.cpu_count() or 2) - 1)) as pool:
        return list(pool.map(one, snippets))
