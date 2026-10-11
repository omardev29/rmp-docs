#!/usr/bin/env bash
python3 - <<'PY'
RULES = {
    "S1": "a C cast",
    "S6": "postfix ++",
}
PY
