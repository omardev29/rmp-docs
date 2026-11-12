"""A tutorial is a real game, built step by step, and every step is built.

A block in a tutorial page says which project and which file it is:

    <pre data-lang="cpp" data-project="my_game" data-file="src/scenes/play.cpp">

The block is that whole file at that step: it replaces whatever an earlier
step put there. A toml block with data-file="raylib_multiplatform.toml" holds
only the keys it changes, under their [section]; the step sets those keys.

`build.py check --tier project` makes the project with the framework's own
`rmp new`, then for every page of the tutorial, in the order the sidebar shows
them: applies that page's files, builds the game for raylib's software
renderer and runs it -- tools/render_check.sh, which says the game booted with
every asset, drew, and exited cleanly -- and, while the game has tests in
tests/game/, runs them the way the reader would: `rmp test unit`. A step that
does not build, does not boot, or fails the game's own tests is a problem on
that page. What a reader types at step N works at step N.

A page that shows the game after it (`/shots/tutorial/<project>/<page>.png`,
shots.py) gets its picture here: the build that just booted runs again for
shots.FRAMES frames and writes its last one.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectFile:
    page: str          # the page's source
    line: int
    path: str          # in the project
    code: str
    lang: str
    copy_from: str = ""   # a framework file the step copies in (art, a sound)


@dataclass
class Step:
    page: str
    files: list = field(default_factory=list)


def set_toml_keys(text: str, edits: str) -> str:
    """Set every `key = value` of `edits`, under its [section], in `text`:
    the key's line is replaced where the section has it, and added at the end
    of the section where it does not; a missing section is added at the end."""
    lines = text.split("\n")
    section = ""
    for raw in edits.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"\[([^\]]+)\]$", line)
        if m:
            section = m.group(1)
            if f"[{section}]" not in (l.strip() for l in lines):
                while lines and not lines[-1].strip():
                    lines.pop()
                lines += ["", f"[{section}]", ""]
            continue
        k = re.match(r"([\w-]+)\s*=\s*(.+)$", line)
        if not k:
            raise ValueError(f"not a `key = value` line: {line!r}")
        key, value = k.group(1), k.group(2)
        head = next(i for i, l in enumerate(lines) if l.strip() == f"[{section}]")
        end = next((i for i in range(head + 1, len(lines)) if lines[i].lstrip().startswith("[")),
                   len(lines))
        found = next((i for i in range(head + 1, end)
                      if re.match(rf"\s*{re.escape(key)}\s*=", lines[i])), None)
        if found is not None:
            lines[found] = f"{key} = {value}"
        else:
            last = max((i for i in range(head, end) if lines[i].strip()), default=head)
            lines.insert(last + 1, f"{key} = {value}")
    return "\n".join(lines)


def apply(project: Path, step: Step, framework: Path | None = None) -> None:
    for f in step.files:
        target = project / f.path
        if f.copy_from:
            import shutil
            source = (framework or Path()) / f.copy_from
            if not source.is_file():
                raise ValueError(f"data-copy-from={f.copy_from!r} is not a file of the framework")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
            continue
        if f.lang == "toml" and f.path == "raylib_multiplatform.toml":
            target.write_text(set_toml_keys(target.read_text(encoding="utf-8"), f.code),
                              encoding="utf-8")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.code.rstrip("\n") + "\n", encoding="utf-8")


def picture(project: Path, name: str, png: Path, scene: tuple | None = None) -> str | None:
    """The game as it is built now, run for shots.FRAMES frames, its last frame
    written to `png`; why not, or None. `scene` (class, header) starts it
    there instead of where src/main.cpp does -- for this run only."""
    from .shots import FRAMES, start_in
    png = png.resolve()
    png.parent.mkdir(parents=True, exist_ok=True)
    main = project / "src" / "main.cpp"
    kept = main.read_text(encoding="utf-8")
    try:
        if scene:
            main.write_text(start_in(kept, *scene), encoding="utf-8")
            built = subprocess.run(["cmake", "--build", "build/memory"], cwd=project,
                                   capture_output=True, text=True)
            if built.returncode != 0:
                said = (built.stdout + built.stderr).strip().splitlines()
                return (f"the game does not build starting in {scene[0]} ({scene[1]}):\n"
                        + "\n".join(said[-15:]))
        env = dict(os.environ, RAY_TEST_MAX_FRAMES=str(FRAMES), RAY_TEST_SCREENSHOT=str(png))
        got = subprocess.run([f"./build/memory/{name}"], cwd=project, env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True)
    except ValueError as e:
        return str(e)
    finally:
        main.write_text(kept, encoding="utf-8")
    if got.returncode != 0 or not png.is_file():
        said = (got.stdout + got.stderr).strip().splitlines()
        return ("the game booted, and its picture for the page was not made (exit "
                f"{got.returncode}):\n" + "\n".join(said[-15:]))
    return None


def run(framework: Path, name: str, steps: list[Step], keep: Path | None = None,
        shots: Path | None = None, wanted: dict | None = None):
    """(step, problem or None) for every step: built and booted in order. A
    step whose page's stem is in `wanted` leaves its picture in `shots`,
    started in the (scene, header) it maps to, or where the game starts."""
    wanted = wanted or {}
    results = []
    framework = framework.resolve()   # rmp new runs from the temporary folder
    with tempfile.TemporaryDirectory() as tmp:
        parent = keep or Path(tmp)
        project = parent / name
        got = subprocess.run([sys.executable, str(framework / "tools" / "rmp.py"), "new", name],
                             cwd=parent, capture_output=True, text=True)
        if got.returncode != 0:
            return [(steps[0] if steps else None, f"rmp new {name} failed:\n{got.stdout}{got.stderr}")]
        for step in steps:
            try:
                apply(project, step, framework)
            except ValueError as e:
                results.append((step, str(e)))
                break
            check = subprocess.run(["sh", "tools/render_check.sh", "Ninja", "", name, "check"],
                                   cwd=project, capture_output=True, text=True)
            if check.returncode != 0:
                said = (check.stdout + check.stderr).strip().splitlines()
                tail = "\n".join(said[-25:])
                results.append((step, f"the project does not build and boot after this page:\n{tail}"))
                break
            # The game's own tests, which rmp new gives every game and the
            # reader's `rmp test` runs: a page that changes what they test has
            # to change them too.
            if any(project.glob("tests/game/*.cpp")):
                unit = subprocess.run([sys.executable, "tools/rmp.py", "test", "unit"],
                                      cwd=project, capture_output=True, text=True)
                if unit.returncode != 0:
                    said = (unit.stdout + unit.stderr).strip().splitlines()
                    tail = "\n".join(said[-25:])
                    results.append((step, "the game's own tests, rmp test unit, fail after this "
                                          f"page:\n{tail}"))
                    break
            stem = Path(step.page).stem
            if shots is not None and stem in wanted:
                why = picture(project, name, shots / f"{stem}.png", wanted[stem])
                if why:
                    results.append((step, why))
                    break
            results.append((step, None))
    return results
