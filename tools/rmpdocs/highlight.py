"""Syntax highlighting at BUILD time: the page ships coloured spans and no
JavaScript highlighter.

Each language is a small scanner -- an ordered list of patterns tried at the
current position -- and the output is the source, escaped, with <span class>
around the tokens worth telling apart. Classes, kept short because every
token on every page carries one:

    k  keyword            (and the toml/json literals true, false, null)
    t  type               int, float, PascalCase names
    f  function           a name followed by "(", a shell command word
    s  string             and #include <header>
    n  number
    c  comment
    p  preprocessor       #include, #define ...
    m  macro / constant   ALL_CAPS names
    a  attribute          [[nodiscard]], --flags, toml keys, yaml keys
    v  variable           $HOME, ${x}

Hierarchy by weight as well as colour: keywords are JetBrains Mono 800 in the
stylesheet, so the structure of a block survives a reader who cannot tell the
colours apart.
"""

from __future__ import annotations

import html
import re

LANGS = ("cpp", "c", "toml", "shell", "powershell", "cmake", "json", "yaml", "text")

CPP_KEYWORDS = set("""
alignas alignof and asm auto break case catch class co_await co_return co_yield concept
const consteval constexpr constinit const_cast continue decltype default delete do
dynamic_cast else enum explicit export extern false final for friend goto if inline
mutable namespace new noexcept not nullptr operator or override private protected public
register reinterpret_cast requires return sizeof static static_assert static_cast struct
switch template this thread_local throw true try typedef typeid typename union using
virtual volatile while
""".split())
C_EXTRA_KEYWORDS = {"restrict", "_Bool", "_Static_assert"}
CPP_TYPES = set("""
void bool char short int long float double signed unsigned size_t ptrdiff_t
int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t intptr_t uintptr_t
char8_t char16_t char32_t wchar_t
""".split())
SHELL_KEYWORDS = set("if then else elif fi for while until do done case esac in function "
                     "return export local set unset".split())
PS_KEYWORDS = set("if else elseif foreach for while do switch function param return throw "
                  "try catch finally exit".split())


def _span(cls: str, text: str) -> str:
    return f'<span class="{cls}">{html.escape(text, quote=False)}</span>'


class Scanner:
    """Patterns are (regex, handler). A handler is a class name, None for
    plain text, or a function(match, scanner) -> html."""

    def __init__(self, rules):
        self.rules = [(re.compile(rx, re.M | re.S), h) for rx, h in rules]

    def run(self, src: str) -> str:
        out = []
        pos = 0
        self.src = src
        plain = []
        while pos < len(src):
            for rx, handler in self.rules:
                m = rx.match(src, pos)
                if m and m.end() > pos:
                    if plain:
                        out.append(html.escape("".join(plain), quote=False))
                        plain = []
                    if handler is None:
                        out.append(html.escape(m.group(0), quote=False))
                    elif isinstance(handler, str):
                        out.append(_span(handler, m.group(0)))
                    else:
                        out.append(handler(m, self))
                    pos = m.end()
                    break
            else:
                plain.append(src[pos])
                pos += 1
        if plain:
            out.append(html.escape("".join(plain), quote=False))
        return "".join(out)


def _cpp_ident(keywords):
    def handler(m, sc):
        word = m.group(0)
        rest = sc.src[m.end():m.end() + 40]
        if word in keywords:
            return _span("k", word)
        if word in CPP_TYPES:
            return _span("t", word)
        if re.match(r"\s*\(", rest):
            return _span("f", word)
        if re.fullmatch(r"[A-Z][A-Z0-9_]+", word):
            return _span("m", word)
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*", word):
            return _span("t", word)
        return html.escape(word, quote=False)
    return handler


def _cpp_preproc(m, sc):
    text = m.group(0)
    d = re.match(r"(\s*#\s*\w+)(.*)", text, re.S)
    head, rest = d.group(1), d.group(2)
    if head.strip().replace(" ", "") == "#include":
        inc = re.match(r"(\s*)(<[^>\n]*>|\"[^\"\n]*\")(.*)", rest, re.S)
        if inc:
            return (_span("p", head) + html.escape(inc.group(1), quote=False)
                    + _span("s", inc.group(2)) + _comment_tail(inc.group(3)))
    return _span("p", head) + _comment_tail(rest, macro=True)


def _comment_tail(rest: str, macro: bool = False) -> str:
    m = re.search(r"//.*$", rest)
    body, comment = (rest[:m.start()], m.group(0)) if m else (rest, "")
    if macro:
        body = re.sub(r"\b([A-Z][A-Z0-9_]{2,})\b",
                      lambda mm: _span("m", mm.group(1)), html.escape(body, quote=False))
    else:
        body = html.escape(body, quote=False)
    return body + (_span("c", comment) if comment else "")


def cpp_scanner(c_only: bool = False) -> Scanner:
    keywords = (CPP_KEYWORDS | C_EXTRA_KEYWORDS) if c_only else CPP_KEYWORDS
    return Scanner([
        (r"//[^\n]*", "c"),
        (r"/\*.*?\*/", "c"),
        (r"^[ \t]*#[ \t]*\w+[^\n]*", _cpp_preproc),
        (r'R"([^(\s]*)\(.*?\)\1"', "s"),
        (r'(?:u8|u|U|L)?"(?:\\.|[^"\\\n])*"', "s"),
        (r"(?:u8|u|U|L)?'(?:\\.|[^'\\\n])+'", "s"),
        (r"\[\[[^\]]*\]\]", "a"),
        (r"\b0[xX][0-9a-fA-F']+[uUlL]*\b", "n"),
        (r"(?:\b\d[\d']*\.?[\d']*|\.\d[\d']*)(?:[eE][+-]?\d+)?[fFuUlL]*\b", "n"),
        (r"[A-Za-z_]\w*", _cpp_ident(keywords)),
        (r"\s+", None),
    ])


def toml_scanner() -> Scanner:
    return Scanner([
        (r"#[^\n]*", "c"),
        (r"^[ \t]*\[\[?[^\]\n]+\]\]?", "k"),
        (r"^[ \t]*[A-Za-z0-9_.\-\"]+(?=[ \t]*=)", "a"),
        (r'"""(?:.|\n)*?"""', "s"),
        (r'"(?:\\.|[^"\\\n])*"', "s"),
        (r"'[^'\n]*'", "s"),
        (r"\b(?:true|false)\b", "k"),
        (r"[+-]?(?:\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?|inf|nan)\b", "n"),
        (r"\s+", None),
    ])


def _shell_word(keywords):
    def handler(m, sc):
        word = m.group(0)
        if word in keywords:
            return _span("k", word)
        # A command word: first on its line, or after a separator.
        before = sc.src[:m.start()]
        tail = before[-40:]
        if re.search(r"(?:^|\n|[;|&(]|&&|\|\||\$\()[ \t]*$", tail) or not before:
            return _span("f", word)
        return html.escape(word, quote=False)
    return handler


def shell_scanner() -> Scanner:
    return Scanner([
        (r"(?:(?<=\s)|^)#[^\n]*", "c"),
        (r"'[^']*'", "s"),
        (r'"(?:\\.|[^"\\])*"', "s"),
        (r"\$\{[^}\n]*\}|\$\(|\$[A-Za-z_]\w*|\$[0-9@#?*$!]", "v"),
        (r"(?:(?<=\s)|^)--?[A-Za-z][\w-]*(?:=\S*)?", "a"),
        (r"[A-Za-z_.~/][\w./~+-]*", _shell_word(SHELL_KEYWORDS)),
        (r"\s+", None),
    ])


def powershell_scanner() -> Scanner:
    def word(m, sc):
        w = m.group(0)
        if w.lower() in PS_KEYWORDS:
            return _span("k", w)
        if re.fullmatch(r"[A-Z][a-z]+-[A-Za-z]+", w):
            return _span("f", w)
        before = sc.src[:m.start()][-40:]
        if re.search(r"(?:^|\n|[;|&(])[ \t]*$", before) or not sc.src[:m.start()]:
            return _span("f", w)
        return html.escape(w, quote=False)
    return Scanner([
        (r"#[^\n]*", "c"),
        (r"'[^']*'", "s"),
        (r'"(?:`.|[^"`])*"', "s"),
        (r"\$\{[^}]*\}|\$[A-Za-z_][\w:]*", "v"),
        (r"\[[A-Za-z][\w.]*\]", "t"),
        (r"(?:(?<=\s)|^)-[A-Za-z][\w-]*", "a"),
        (r"[A-Za-z_.~/\\][\w./~\\+-]*", word),
        (r"\s+", None),
    ])


def cmake_scanner() -> Scanner:
    return Scanner([
        (r"#[^\n]*", "c"),
        (r'"(?:\\.|[^"\\])*"', "s"),
        (r"\$\{[^}\n]*\}", "v"),
        (r"[A-Za-z_]\w*(?=\s*\()", "f"),
        (r"\b[A-Z][A-Z0-9_]+\b", "m"),
        (r"\s+", None),
    ])


def json_scanner() -> Scanner:
    return Scanner([
        (r'"(?:\\.|[^"\\])*"(?=\s*:)', "a"),
        (r'"(?:\\.|[^"\\])*"', "s"),
        (r"\b(?:true|false|null)\b", "k"),
        (r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", "n"),
        (r"\s+", None),
    ])


def yaml_scanner() -> Scanner:
    return Scanner([
        (r"(?:(?<=\s)|^)#[^\n]*", "c"),
        (r"^[ \t]*-?[ \t]*[\w.\-]+(?=:(?:\s|$))", "a"),
        (r"'[^'\n]*'", "s"),
        (r'"(?:\\.|[^"\\\n])*"', "s"),
        (r"\$\{\{[^}]*\}\}", "v"),
        (r"\b(?:true|false|null|yes|no)\b", "k"),
        (r"\s+", None),
    ])


_SCANNERS = {}


def highlight(src: str, lang: str) -> str:
    if lang not in LANGS:
        raise ValueError(f"no highlighter for {lang!r}; one of {', '.join(LANGS)}")
    if lang == "text":
        return html.escape(src, quote=False)
    if lang not in _SCANNERS:
        _SCANNERS[lang] = {
            "cpp": lambda: cpp_scanner(),
            "c": lambda: cpp_scanner(c_only=True),
            "toml": toml_scanner,
            "shell": shell_scanner,
            "powershell": powershell_scanner,
            "cmake": cmake_scanner,
            "json": json_scanner,
            "yaml": yaml_scanner,
        }[lang]()
    return _SCANNERS[lang].run(src)


def plain(highlighted: str) -> str:
    """The source back out of the highlighted HTML: what a test compares."""
    return html.unescape(re.sub(r"<[^>]+>", "", highlighted))
