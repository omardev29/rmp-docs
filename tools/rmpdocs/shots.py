"""The pictures a page shows are made from code, never by hand.

A screenshot taken by hand goes stale the day the interface changes, and
nothing says so. So a raster image in a page is one of two kinds, both made
by the code they show, every time the site is built:

    /shots/e2e/<area>/<example>/<shot>.png
        a golden of the framework's e2e scripts,
        tests/e2e/golden/<area>/<example>/<shot>.png at FRAMEWORK_REF: the
        frame the script compares exactly, in the pinned image, on every push.
        A golden that moves moves here with the next FRAMEWORK_REF; one that is
        gone is a problem on the page that shows it.

    /shots/tutorial/<project>/<page>.png
        the tutorial's game after that page: the project tier (project.py)
        builds the game with the page's files for raylib's software renderer
        and keeps its frame number FRAMES. <page> is the file name of a page
        that writes files of <project>, without .html. The game starts where
        it always does (src/main.cpp's RMP_GAME) unless the image names
        another scene: data-scene="GameScene" data-header="scenes/game.h",
        a class the tutorial wrote and the header it is declared in -- for the
        picture only, the build after it starts where the reader's does.

A fragment writes the address from the site's root; the build makes it
relative, copies the e2e goldens it names, and the project tier writes the
tutorial's.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = "shots/"
E2E = "shots/e2e/"
TUTORIAL = "shots/tutorial/"
GOLDEN = "tests/e2e/golden/"
FRAMES = 240          # four seconds at the smoke run's 1/60 s: fades over, things moving
RASTER = re.compile(r"\.(png|jpe?g|gif|webp|avif|bmp)(\?|$)", re.I)
_PROJECT = re.compile(r"""data-project\s*=\s*["']([^"']+)["']""")
_PART = re.compile(r"[A-Za-z0-9_.-]+")


def site_path(src: str) -> str | None:
    """The site path of a shot ("shots/e2e/..."), or None when `src` is no shot."""
    if not src.startswith("/" + ROOT):
        return None
    return src[1:].partition("#")[0].partition("?")[0]


def golden_of(path: str) -> str:
    """The framework file an e2e shot is: shots/e2e/a/b/c.png -> tests/e2e/golden/a/b/c.png."""
    return GOLDEN + path[len(E2E):]


def tutorial_shot(project: str, page_source: str) -> str:
    """The site path of the tutorial's game after a page."""
    return f"{TUTORIAL}{project}/{Path(page_source).stem}.png"


def tutorial_steps(sources: dict) -> set:
    """Every (project, page stem) a tutorial has a picture for: the pages that
    write files of a project."""
    return {(name, Path(path).stem) for path, text in sources.items()
            for name in _PROJECT.findall(text)}


_SCENE = re.compile(r"[A-Z][A-Za-z0-9_]*")
_HEADER = re.compile(r"[a-z0-9_]+(/[a-z0-9_]+)*\.h")


def project_headers(sources: dict) -> dict:
    """project -> every header under src/ a tutorial page writes, below src/."""
    out: dict = {}
    pre = re.compile(r"<pre\b[^>]*>", re.I)
    for text in sources.values():
        for tag in pre.findall(text):
            proj = _PROJECT.search(tag)
            f = re.search(r"""data-file\s*=\s*["']src/([^"']+\.h)["']""", tag)
            if proj and f:
                out.setdefault(proj.group(1), set()).add(f.group(1))
    return out


def why_not_scene(src: str, scene: str, header: str, headers: dict) -> str | None:
    """Why an image's data-scene/data-header cannot start its picture; None
    when it can, or when it names neither."""
    if not scene and not header:
        return None
    path = site_path(src) or ""
    if not path.startswith(TUTORIAL):
        return f"{src}: data-scene and data-header start a picture of the tutorial's game, and this is none"
    if not scene or not header:
        return f"{src}: data-scene and data-header go together: the scene and the header that declares it"
    if not _SCENE.fullmatch(scene):
        return f"{src}: data-scene={scene!r} is not the name of a class"
    project = path.split("/")[2]
    if not _HEADER.fullmatch(header) or header not in headers.get(project, set()):
        return (f"{src}: data-header={header!r} is no header the tutorial {project!r} writes "
                f"(a data-file=\"src/...\" of its pages, written below src/)")
    return None


def start_in(main_cpp: str, scene: str, header: str) -> str:
    """src/main.cpp starting in `scene` instead: its header included, and
    RMP_GAME naming it."""
    out, n = re.subn(r"RMP_GAME\(\s*\w+\s*\)", f"RMP_GAME({scene})", main_cpp)
    if n != 1:
        raise ValueError("src/main.cpp has no RMP_GAME(...) to start another scene with")
    return f'#include "{header}"\n' + out


def why_not(src: str, read_golden, steps: set) -> str | None:
    """Why `src` is not a picture a page may show; None when it is.
    `read_golden(path)` gives a framework file at FRAMEWORK_REF or raises
    LookupError."""
    path = site_path(src)
    kinds = (f"/{E2E}<area>/<example>/<shot>.png, a golden of the framework's e2e scripts, or "
             f"/{TUTORIAL}<project>/<page>.png, the tutorial's game after that page")
    if path is None:
        return (f"{src}: a raster image in a page is a picture the build makes from code -- "
                f"{kinds}; a screenshot taken by hand goes stale the day the interface changes")
    parts = path.split("/")
    if not all(_PART.fullmatch(p) and p not in (".", "..") for p in parts) or not path.endswith(".png"):
        return f"{src}: not an address of a shot ({kinds})"
    if path.startswith(E2E) and len(parts) == 5:
        try:
            read_golden(golden_of(path))
        except LookupError:
            return (f"{src}: the framework has no {golden_of(path)} at FRAMEWORK_REF -- "
                    f"no e2e script takes that shot")
        return None
    if path.startswith(TUTORIAL) and len(parts) == 4:
        project, stem = parts[2], parts[3][:-len(".png")]
        if (project, stem) not in steps:
            return (f"{src}: no page called {stem}.html writes files of the tutorial "
                    f"{project!r}, so the project tier makes no such picture")
        return None
    return f"{src}: not an address of a shot ({kinds})"
