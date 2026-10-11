#!/usr/bin/env bash
# Mutation testing of tools/rmpdocs: when the code is made wrong on purpose,
# does a test fail?
#
# The framework's tools/mutation.sh, for this repository. mutmut 3 changes
# one operator, constant or call at a time -- a mutant -- and runs the tests
# that reach that function against it. A mutant no test notices is a test
# nobody wrote, or an equivalent change nobody can see.
#
# What is mutated, which tests must notice and the score that has to hold
# are tests/mutation/floors/<module>.txt, in the framework's format, and the
# verdict is the framework's own tools/mutation_report.py reading what
# mutmut wrote (its .meta files, never what it printed): one checker, for
# the framework and for its documentation. The framework is RMP_FRAMEWORK,
# or ../raylib_multiplatform, as everywhere else here.
#
#   bash tests/mutation/run.sh run [MODULE]      mutate, run the tests, check the floor
#   bash tests/mutation/run.sh check [MODULE]    the last run against the floor again
#   bash tests/mutation/run.sh update [MODULE]   the same, raising the floor to what it earned
#
# MODULE is rmpdocs, the only one so far. mutmut, Hypothesis and pytest are
# in the framework's pinned build image, where the floor was measured:
#
#   podman run --rm --init -v "$PWD":/work -w /work -e RMP_FRAMEWORK=<it> \
#     ghcr.io/omardev29/raylib-build@sha256:<digest> bash tests/mutation/run.sh run
#
# mutmut works on a copy, in .cache/mutation/<module>/: of what git tracks
# and what it would (untracked, not ignored) -- the tests find the repository
# from their own path, so inside the copy they read the mutated file. Code
# a test reaches only through a subprocess counts as reached by none:
# mutmut follows calls in-process.
#
# ASCII only and no GNU-only constructs: macOS ships bash 3.2.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

FLOORS="tests/mutation/floors"
BUILD=".cache/mutation"

usage() {
  echo "usage: bash tests/mutation/run.sh run|check|update [MODULE]"
  exit 2
}

framework() {
  local fw="${RMP_FRAMEWORK:-../raylib_multiplatform}"
  # Said on stderr: this runs inside $(...), which keeps stdout.
  if [ ! -f "$fw/tools/mutation_report.py" ]; then
    echo "FAIL: no tools/mutation_report.py in the framework at '$fw': set RMP_FRAMEWORK to a" >&2
    echo "      checkout of raylib_multiplatform that has it (the deep test campaign, phase 16)." >&2
    exit 1
  fi
  (cd "$fw" && pwd)
}

report() {
  local module="$1"
  shift
  python3 "$FW/tools/mutation_report.py" "$module" --floors "$FLOORS" "$@"
}

known() {
  if [ ! -f "$FLOORS/$1.txt" ]; then
    echo "FAIL: no module called '$1': there is no $FLOORS/$1.txt"
    exit 2
  fi
  if [ "$(report "$1" --print kind)" != py ]; then
    echo "FAIL: $FLOORS/$1.txt is not kind py: this repository is Python"
    exit 2
  fi
}

check() {
  local module="$1" update="${2:-}" args=() source
  while IFS= read -r source; do
    [ -n "$source" ] && args+=(--mutmut "$BUILD/$module/mutants/$source.meta")
  done < <(report "$module" --print sources)
  report "$module" "${args[@]}" ${update:+"$update"}
}

run() {
  local module="$1" dir="$BUILD/$1" sources tests selects entry stems
  if ! command -v mutmut > /dev/null 2>&1; then
    echo "FAIL: no mutmut here. mutmut 3.8.0 is in the framework's pinned build image."
    exit 1
  fi
  if [ "$(git rev-parse --is-inside-work-tree 2> /dev/null || true)" != true ]; then
    echo "FAIL: mutmut works on a copy of what git tracks, and git cannot read this checkout"
    echo "      (a worktree whose .git is not here, or a folder git does not trust:"
    echo "      git config --global --add safe.directory \"\$PWD\")."
    exit 1
  fi
  echo "== mutation: copy the tree for $module =="
  rm -rf "$dir"
  mkdir -p "$dir"
  git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf - | tar -xf - -C "$dir"
  sources=$(report "$module" --print sources)
  tests=$(report "$module" --print tests)
  selects=$(report "$module" --print select)
  stems=""
  for entry in $sources; do
    case "$entry" in
      tools/rmpdocs/*.py) stems="$stems \"$(basename "$entry" .py)\"," ;;
      *) echo "FAIL: $entry: a source here is a module of tools/rmpdocs/"; exit 2 ;;
    esac
  done
  # The older tests import `rmpdocs.<name>`, and mutmut knows the file as
  # `tools.rmpdocs.<name>`: one module under both names, so they count too.
  cat > "$dir/conftest.py" <<PY
# Written by tests/mutation/run.sh, in mutmut's copy of the tree only.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
from under_test import load  # noqa: E402

for _name in ($stems):
    sys.modules["rmpdocs." + _name] = load(_name)
PY
  {
    echo "[mutmut]"
    echo "source_paths ="
    # shellcheck disable=SC2086  # one path a word
    printf '    %s\n' $sources
    echo "pytest_add_cli_args_test_selection ="
    # shellcheck disable=SC2086
    printf '    %s\n' $tests
    echo "pytest_add_cli_args ="
    printf '    %s\n' -q -p no:cacheprovider
    echo "also_copy ="
    for entry in $(cd "$dir" && ls -A); do
      case "$entry" in mutants | setup.cfg) continue ;; esac
      echo "    $entry"
    done
  } > "$dir/setup.cfg"
  # shellcheck disable=SC2086  # one path a word
  echo "== mutation: mutmut over$(printf ' %s' $sources) =="
  # Its exit status is not the verdict -- the .meta files it wrote are, and
  # mutation_report.py fails a mutant it never got to. It is printed.
  local status=0
  # shellcheck disable=SC2086  # selects are words on purpose, and none means all
  (cd "$dir" && RMP_FRAMEWORK="$FW" mutmut run --max-children "${CMAKE_BUILD_PARALLEL_LEVEL:-4}" $selects < /dev/null) \
    > "$dir.log" 2>&1 || status=$?
  tail -5 "$dir.log" | sed 's/^/  /'
  echo "  mutmut exited $status"
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage
command="$1"
module="${2:-rmpdocs}"
FW=$(framework)
known "$module"
case "$command" in
  run) run "$module"; check "$module" ;;
  check) check "$module" ;;
  update) check "$module" --update ;;
  *) usage ;;
esac
