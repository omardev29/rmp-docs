import json, sys
if sys.argv[1:] == ["--print-schema"]:
    print(json.dumps([{"key": "window.width"}, {"key": "window.height"}, {"key": "audio.enabled"}]))
else:
    sys.exit(2)
