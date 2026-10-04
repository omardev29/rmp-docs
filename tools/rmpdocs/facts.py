"""What the pages quote from the framework instead of typing: counts and lists.

A page writes {{count:targets}} or {{list:targets}}; the build puts the
framework's number in, read from the framework at FRAMEWORK_REF. A digit typed
next to one of these nouns is what the `counts` gate refuses, because "the
14-target CI" is how this project's own design document lied for a phase.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


class Facts:
    def __init__(self, framework: Path):
        self.framework = framework
        self._configure = None

    @property
    def configure(self):
        if self._configure is None:
            tools = self.framework / "tools"
            spec = importlib.util.spec_from_file_location("rmp_docs_configure", tools / "configure.py")
            module = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(tools))
            try:
                spec.loader.exec_module(module)
            finally:
                sys.path.remove(str(tools))
            self._configure = module
        return self._configure

    def examples(self) -> list[str]:
        found = set()
        root = self.framework / "examples"
        for main in list(root.glob("**/src/main.cpp")) + list(root.glob("**/src/main.c")):
            found.add(main.parent.parent.relative_to(root).as_posix())
        return sorted(found)

    def headers(self) -> list[str]:
        return sorted(p.name for p in (self.framework / "include" / "rmp").glob("*.h"))

    def value(self, kind: str, name: str) -> str:
        if kind == "count":
            if name == "targets":
                return str(len(self.configure.TARGETS))
            if name == "families":
                return str(len({f for f, _ in self.configure.TARGETS.values()}))
            if name == "examples":
                return str(len(self.examples()))
            if name == "games":
                return str(len([e for e in self.examples() if e.startswith("games/")]))
            if name == "headers":
                return str(len(self.headers()))
        if kind == "list":
            if name == "targets":
                return ", ".join(label for _f, label in self.configure.TARGETS.values())
            if name == "target-ids":
                return ", ".join(self.configure.TARGETS)
        raise KeyError(f"{{{{{kind}:{name}}}}} is not a fact the build knows")
