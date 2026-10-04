import json, sys
if sys.argv[1:] == ["help", "--json"]:
    print(json.dumps({"commands": [
        {"name": "run", "usage": "run", "framework_only": False},
        {"name": "new", "usage": "new DIR", "framework_only": False},
        {"name": "lint", "usage": "lint", "framework_only": True}], "stages": []}))
else:
    sys.exit(2)
