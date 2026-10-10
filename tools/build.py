#!/usr/bin/env python3
"""rmp-docs: builds and checks the documentation site of raylib_multiplatform.

    python3 tools/build.py build            write _site/, then run every gate
    python3 tools/build.py check            the gates, without writing
    ... --tier compile                      and compile every C and C++ block against
                                            the framework (needs its build/lint configured)
    python3 tools/build.py serve [PORT]     build, then serve _site/ on localhost
    python3 tools/build.py gates            list the gates and what each one says

The framework is found with --framework PATH, $RMP_FRAMEWORK, or next to this
repository as ../raylib_multiplatform. FRAMEWORK_REF says which commit the site
documents; building against anything else says so.

Standard library only, Python 3.11 or newer.
"""

import sys

if sys.version_info < (3, 11):
    sys.exit("build.py needs Python 3.11 or newer (tomllib); this is %d.%d" % sys.version_info[:2])

import argparse
import functools
import http.server
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rmpdocs import checks, coverage, truth  # noqa: E402,F401 - they register their gates
from rmpdocs.site import Site  # noqa: E402


def context(site: Site) -> checks.Context:
    config = dict(site.config, _search_json=getattr(site, "search_json", None))
    ctx = checks.Context(docs=site.docs, outputs=site.outputs, config=config,
                         build_problems=site.problems, framework=site.framework,
                         refconf=site.refconf, served=site.served, ref=site.ref)
    for page in site.pages:
        if page.kind == "content":
            ctx.sources[page.source] = (site.docs / page.source).read_text(encoding="utf-8")
    return ctx


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("build", "check", "serve", "gates"))
    ap.add_argument("port", nargs="?", type=int, default=8040)
    ap.add_argument("--framework", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--examples-web", type=Path, metavar="DIR",
                    help="the framework's web build of the examples (build/web): played in their pages")
    ap.add_argument("--posters", type=Path, metavar="DIR",
                    help="the examples job's screenshots, one <target>.png each")
    ap.add_argument("--tier", choices=("static", "compile", "project"), default="static",
                    help="static: the gates; compile: and every C/C++ block compiled; "
                         "project: and every tutorial built and booted, step by step")
    args = ap.parse_args(argv)

    if args.command == "gates":
        for name, (_fn, says) in checks.GATES.items():
            print(f"{name:16} {says}")
        return 0

    site = Site(framework=args.framework, out=args.out, examples_web=args.examples_web,
                posters=args.posters).build(write=args.command != "check")
    for w in site.warnings:
        print(f"warning: {w}")
    problems = [p for p in site.problems if p.gate != "html"] + checks.run(context(site))
    if args.tier in ("compile", "project"):
        from rmpdocs import snippets
        results = snippets.check(site.snippets, site.framework)
        for s, why in results:
            if why:
                problems.append(checks.Problem("snippets", s.page, s.line, why))
        print(f"compiled {len(results)} C/C++ blocks against the framework")
    if args.tier == "project":
        from rmpdocs import project
        for name, steps in site.project_steps().items():
            for step, why in project.run(site.framework, name, steps):
                if why:
                    problems.append(checks.Problem("project", step.page if step else name, 0, why))
                else:
                    print(f"  ok    {name}: built and booted after {step.page}")
    for p in problems:
        print(p)
    pages = len(site.pages)
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {pages} pages")
        return 1
    print(f"PASS: {pages} pages, {len(checks.GATES)} gates")
    if args.command == "serve":
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site.out))
        print(f"serving {site.out} at http://localhost:{args.port}/  (Ctrl-C to stop)")
        http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
