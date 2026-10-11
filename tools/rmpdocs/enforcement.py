"""The Guidelines say which tool holds each rule, and where. This gate holds
what they say to the framework's own configuration.

A page states it in a table marked `data-enforcement`, one rule a row and
five cells: the rule, what checks it, and whether it holds in the framework
(include/, src/, tests/), in the examples, and in a game `rmp new` makes. A
scope cell that starts with "no" says no; anything else says yes. What the
second cell names in <code> is read as:

    modernize-avoid-c-arrays     a clang-tidy check: the framework's
                                 .clang-tidy has to run it in every scope the
                                 row says yes to -- examples/.clang-tidy for
                                 the examples -- and in none it says no to
    tools/style_check.sh S6      a gate of the framework's, and a rule of it:
                                 the rule has to be one the script defines
    -Werror=reorder-init-list    a compiler flag: CMakeLists.txt has to pass it
    .clang-format                a file of the framework's

and a game is said to get a tool only when `rmp new` copies it into one (a
check is the game's when its .clang-tidy is; a flag, when CMakeLists.txt
passes it). And the other way round: every check the framework's
.clang-tidy files name -- switched on by name or switched off -- and each
of its CustomChecks, appears on a Guidelines page, so that turning one on
or off is a change the site has to answer for.

The .clang-tidy is read here as clang-tidy reads its `Checks`: globs in
order, a leading `-` switching off, the last match deciding;
examples/.clang-tidy appends its own to the root's (InheritParentConfig).
"""

from __future__ import annotations

import fnmatch
import functools
import re
from pathlib import Path

from .checks import Context, Problem, gate
from .truth import _fragments, game_paths

FAMILY = re.compile(r"^(?:abseil|altera|android|boost|bugprone|cert|clang-analyzer|clang-diagnostic|"
                    r"concurrency|cppcoreguidelines|darwin|fuchsia|google|hicpp|linuxkernel|llvm|"
                    r"llvmlibc|misc|modernize|mpi|objc|openmp|performance|portability|readability|"
                    r"zircon|custom)-[A-Za-z0-9._-]+$")
RULE = re.compile(r"^[A-Z]\d+$")
FLAG = re.compile(r"^-W[\w=+-]+$")
FILE = re.compile(r"^(?:tools/[\w.-]+|\.clang-format|\.clang-tidy|examples/\.clang-tidy|CMakeLists\.txt)$")


def checks_globs(text: str) -> list[str]:
    """The `Checks:` value of a .clang-tidy, as a list of globs: a folded
    block (`Checks: >` and its indented lines) or a one-line string."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^Checks:\s*(.*)$", line)
        if not m:
            continue
        value = m.group(1).strip()
        if value in (">", "|", ">-", "|-", ""):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[:1].isspace():
                    break
                body.append(nxt)
            value = " ".join(body)
        value = value.strip("'\"")
        return [g for g in re.split(r"[\s,]+", value) if g]
    return []


def custom_names(text: str) -> list[str]:
    """custom-<Name> of each query under CustomChecks."""
    m = re.search(r"^CustomChecks:\s*$(.*?)(?=^\S)", text + "\nEND", re.M | re.S)
    return [f"custom-{n}" for n in re.findall(r"^\s*-\s*Name:\s*([\w.-]+)", m.group(1), re.M)] if m else []


def enabled(check: str, globs: list[str]) -> bool:
    on = False
    for g in globs:
        negative = g.startswith("-")
        if fnmatch.fnmatchcase(check, g.lstrip("-")):
            on = not negative
    return on


@functools.lru_cache(maxsize=4)
def configuration(framework: str) -> dict | None:
    """The framework's clang-tidy configuration as this gate needs it, or
    None when it has no .clang-tidy."""
    fw = Path(framework)
    root_file = fw / ".clang-tidy"
    if not root_file.is_file():
        return None
    root_text = root_file.read_text(encoding="utf-8")
    root = checks_globs(root_text)
    examples = list(root)
    ex_file = fw / "examples" / ".clang-tidy"
    ex_globs = []
    if ex_file.is_file():
        ex_text = ex_file.read_text(encoding="utf-8")
        ex_globs = checks_globs(ex_text)
        inherit = re.search(r"^InheritParentConfig:\s*true\s*$", ex_text, re.M) is not None
        examples = (root if inherit else []) + ex_globs
    named = {g.lstrip("-") for g in root + ex_globs if "*" not in g}
    customs = custom_names(root_text)
    return {"root": root, "examples": examples, "named": named | set(customs)}


def script_rules(fw: Path, script: str) -> set[str] | None:
    f = fw / script
    if not f.is_file():
        return None
    return set(re.findall(r'^\s*"([A-Z]\d+)"\s*:', f.read_text(encoding="utf-8", errors="replace"), re.M))


def cmake_flags(fw: Path) -> str:
    """CMakeLists.txt without its comments: a flag named only in a comment is
    not one the build passes."""
    f = fw / "CMakeLists.txt"
    if not f.is_file():
        return ""
    return "\n".join(line.split("#", 1)[0] for line in f.read_text(encoding="utf-8").splitlines())


def _cells(row):
    return [c for c in row.children if getattr(c, "tag", None) in ("td", "th")]


def _codes(node) -> list[str]:
    return [n.text().strip() for n in node.walk() if n.tag == "code"]


@gate("enforcement", "the Guidelines' table of what checks what is the framework's: each clang-tidy "
                     "check it names runs in every scope the row says, and in none it says no to; "
                     "each gate rule is one its script defines; a game gets only what rmp new "
                     "copies; and every check the framework's .clang-tidy names, on or off, is on "
                     "a Guidelines page")
def check_enforcement(ctx: Context) -> list[Problem]:
    fw = ctx.framework
    if fw is None:
        return []
    conf = configuration(str(fw))
    if conf is None:
        return []
    game = game_paths(str(fw))
    flags_text = cmake_flags(fw)
    out = []
    tables = 0
    said = set()   # every <code> on a Guidelines page
    for path, root in _fragments(ctx):
        if not path.startswith("content/guidelines/"):
            continue
        said |= set(_codes(root))
        for table in [n for n in root.walk() if n.tag == "table" and "data-enforcement" in n.attrs]:
            tables += 1
            body = next((c for c in table.children if getattr(c, "tag", None) == "tbody"), table)
            for row in [c for c in body.children if getattr(c, "tag", None) == "tr"]:
                out += _row(path, row, fw, conf, game, flags_text)
    if tables == 0:
        out.append(Problem("enforcement", "content/guidelines/", 0,
                           "no Guidelines page has the table of what checks what "
                           "(<table data-enforcement>), and the framework has a .clang-tidy"))
    for name in sorted(conf["named"] - said):
        out.append(Problem("enforcement", "content/guidelines/", 0,
                           f"the framework's .clang-tidy names {name}, and no Guidelines page does: "
                           "say what rule it holds, or why it is switched off"))
    return out


def _row(path, row, fw, conf, game, flags_text) -> list[Problem]:
    cells = _cells(row)
    rule = cells[0].text().strip() if cells else ""
    where = f"`{rule[:60]}`"
    if len(cells) != 5:
        return [Problem("enforcement", path, row.line,
                        f"{where}: a row has five cells -- the rule, what checks it, the framework, "
                        f"the examples, a game -- and this one has {len(cells)}")]
    out = []
    codes = _codes(cells[1])
    checks = [c for c in codes if FAMILY.match(c)]
    rules = [c for c in codes if RULE.match(c)]
    flags = [c for c in codes if FLAG.match(c)]
    files = [c for c in codes if FILE.match(c)]
    if not (checks or flags or files):
        out.append(Problem("enforcement", path, row.line,
                           f"{where} names no tool: a clang-tidy check, a script of tools/, a flag "
                           "or a file of the framework's, in <code>"))
    for f in files:
        if not (fw / f).is_file():
            out.append(Problem("enforcement", path, row.line, f"{where}: the framework has no {f}"))
    known = set()
    for f in files:
        known |= script_rules(fw, f) or set()
    for r in rules:
        if r not in known:
            scripts = ", ".join(f for f in files if f.startswith("tools/")) or "no script the row names"
            out.append(Problem("enforcement", path, row.line,
                               f"{where}: {r} is not a rule of {scripts}"))
    for c in checks:
        if not (enabled(c, conf["root"]) or enabled(c, conf["examples"])):
            out.append(Problem("enforcement", path, row.line,
                               f"{where}: the framework's .clang-tidy does not run {c}, anywhere"))
    for f in flags:
        if f not in flags_text:
            out.append(Problem("enforcement", path, row.line,
                               f"{where}: CMakeLists.txt does not pass {f}"))

    def says(cell) -> bool:
        return not cell.text().strip().lower().startswith("no")

    # The framework and the examples: a check counts where its .clang-tidy
    # runs it. A script or a flag is the framework's own and is taken at its
    # word there; it never makes a "no" wrong.
    for cell, scope, globs in ((cells[2], "the framework", conf["root"]),
                               (cells[3], "the examples", conf["examples"])):
        on = [c for c in checks if enabled(c, globs)]
        if says(cell) and not (on or files or flags):
            out.append(Problem("enforcement", path, row.line,
                               f"{where} says it holds in {scope}, and none of "
                               f"{', '.join(checks) or 'its tools'} runs there"))
        if not says(cell) and on:
            out.append(Problem("enforcement", path, row.line,
                               f"{where} says no for {scope}, and the framework's .clang-tidy runs "
                               f"{', '.join(on)} there"))
    # A game: what rmp new copies, and what CMakeLists.txt hands its target.
    reaching = [f for f in files if f in game] + [f for f in flags if f in flags_text]
    if ".clang-tidy" in game:
        reaching += checks
    if says(cells[4]) and not reaching:
        out.append(Problem("enforcement", path, row.line,
                           f"{where} says a game gets it, and rmp new copies none of "
                           f"{', '.join(checks + files + flags)} into one"))
    if not says(cells[4]) and reaching:
        out.append(Problem("enforcement", path, row.line,
                           f"{where} says no for a game, and a game gets {', '.join(reaching)}"))
    return out
