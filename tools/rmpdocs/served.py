"""Files of the framework the site serves as they are: the installers.

    curl -fsSL https://omardev29.github.io/rmp-docs/install.sh | sh

is a line people paste into a terminal, and what it runs is whatever this
site serves at that address. So the site serves the framework's own
tools/install.sh and tools/install.ps1 -- site.toml [served] names them --
and the `installer` gate holds the served bytes to the framework's at
FRAMEWORK_REF: read from git at that commit, not from whatever the checkout
holds, with the line endings the framework's .gitattributes gives each one.
That last part is not a detail. git stores install.ps1 with LF and writes it
out with CRLF (`*.ps1 text eol=crlf`), because Windows PowerShell 5.1 is what
reads it; `git show REF:tools/install.ps1` is the LF one.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path


def eol_rule(attributes: str, path: str) -> str:
    """"crlf", "lf" or "" for `path`, from the text of a .gitattributes: the
    last line whose pattern matches sets it, as git reads the file. `-text`
    and `binary` mean no conversion at all."""
    rule = ""
    name = path.rsplit("/", 1)[-1]
    for line in attributes.splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        pattern, attrs = words[0], words[1:]
        target = path if "/" in pattern.lstrip("/") else name
        if not fnmatch.fnmatchcase(target, pattern.lstrip("/")):
            continue
        for a in attrs:
            if a in ("-text", "binary"):
                rule = ""
            elif a.startswith("eol="):
                rule = a[4:]
    return rule if rule in ("crlf", "lf") else ""


def normalise(data: bytes, eol: str) -> bytes:
    """The bytes as a checkout with that eol writes them."""
    if not eol:
        return data
    lf = data.replace(b"\r\n", b"\n")
    return lf.replace(b"\n", b"\r\n") if eol == "crlf" else lf


def at_ref(framework: Path, ref: str, path: str) -> bytes:
    """A file of the framework as it is at `ref`, from git. A framework that is
    not a git checkout -- a gate's fixture -- is read as it is on disk.
    LookupError says why it cannot be read."""
    if not (framework / ".git").exists():
        f = framework / path
        if not f.is_file():
            raise LookupError(f"the framework has no {path}")
        return f.read_bytes()
    got = subprocess.run(["git", "-C", str(framework), "show", f"{ref}:{path}"],
                         capture_output=True)
    if got.returncode != 0:
        said = got.stderr.decode("utf-8", "replace").strip()
        raise LookupError(f"git cannot read {path} at FRAMEWORK_REF {ref[:8]}: {said}")
    return got.stdout


def expected(framework: Path, ref: str, path: str) -> tuple[bytes, str]:
    """What the site has to serve for the framework's `path`, and the eol
    that makes it so."""
    try:
        attributes = at_ref(framework, ref, ".gitattributes").decode("utf-8", "replace")
    except LookupError:
        attributes = ""
    rule = eol_rule(attributes, path)
    return normalise(at_ref(framework, ref, path), rule), rule


def from_checkout(framework: Path, path: str) -> bytes:
    """What the build serves: the file in the framework's checkout, with the
    line endings its .gitattributes gives it -- the same bytes whichever way
    the checkout was made."""
    attributes = framework / ".gitattributes"
    text = attributes.read_text(encoding="utf-8", errors="replace") if attributes.is_file() else ""
    return normalise((framework / path).read_bytes(), eol_rule(text, path))


def first_difference(a: bytes, b: bytes) -> int:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))
