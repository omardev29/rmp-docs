import sys
if sys.argv[1:] == ["new", "--list"]:
    print(".clang-format\nCMakeLists.txt\nsrc/main.cpp")
else:
    sys.exit(2)
