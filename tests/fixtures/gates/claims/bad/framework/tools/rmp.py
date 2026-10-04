import json, sys
args = sys.argv[1:]
if args == ["help", "--json"]:
    print(json.dumps({"commands": [
        {"name": "run", "usage": "run"}, {"name": "test", "usage": "test [stage]"},
        {"name": "build", "usage": "build [release]"}, {"name": "example", "usage": "example [name]"},
        {"name": "new", "usage": "new DIR"}, {"name": "help", "usage": "help [command]"}],
        "stages": [{"name": "config"}, {"name": "smoke"}]}))
elif args == ["new", "--list"]:
    print("README.md\nsrc/main.cpp\nraylib_multiplatform.toml")
else:
    sys.exit(2)
