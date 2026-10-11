"""The modules of tools/rmpdocs/ that the property tests and their named
counterexamples exercise, loaded as `tools.rmpdocs.<name>`.

That is the name mutmut gives the file (tests/mutation/run.sh): it records
which tests reach a function under the module's own name, and a test that
imported it as plain `rmpdocs.<name>` -- as the older tests here do --
reaches nothing it can mutate. By its path, too, so that no installed
package called `tools` can stand in for this folder.

`tools` and `tools.rmpdocs` are made packages of these two folders and of
nothing else, so a relative import inside a module works, and so does
`from tools.rmpdocs import dom` (Hypothesis says what a strategy is by
importing the module its lambda came from). The run's conftest.py makes
`rmpdocs.<name>` the same module, so the older tests count as well.

Standard library only: tests/test_counterexamples.py runs without
Hypothesis.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent


def _package(name: str, folder: Path):
    package = sys.modules.get(name)
    if package is None:
        package = types.ModuleType(name)
        package.__path__ = [str(folder)]
        package.__package__ = name
        sys.modules[name] = package
    return package


def load(name: str):
    tools = _package("tools", DOCS / "tools")
    tools.rmpdocs = _package("tools.rmpdocs", DOCS / "tools" / "rmpdocs")
    return importlib.import_module(f"tools.rmpdocs.{name}")
