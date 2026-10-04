"""Reads include/rmp/*.h into entities with their comments.

THE GRAMMAR the headers are written in, and the only one this reads:

  - The FILE BLOCK: the first comment block between two `// ----` lines,
    after `#pragma once`. It is the header's own page text.
  - A BANNER: `// ----` lines around a comment block, inside a namespace or a
    class. Directly above a class, struct or enum it is that type's doc.
    Anywhere else it opens a GROUP of declarations and is the group's intro;
    the declaration right under it is covered by it.
  - A DOC BLOCK: `//` lines directly above a declaration -- no blank line in
    between -- document it. Declarations that follow each other with no blank
    line and no comment between them are a RUN, and the doc above the first
    documents the run (`_suspend()` and `_resume()` under one sentence).
  - A TRAILING comment, on the line a field or an enum member ends.
  - `namespace detail` and members whose name starts with `detail_` are the
    framework's, not the game's: read, kept, marked internal.
  - `private:` and `protected:` sections are not API.

Anything this cannot classify is an error naming the header and the line,
never a silent skip: a declaration the reference does not show is one the
site cannot say is documented.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

BANNER = re.compile(r"^\s*//\s*-{10,}\s*$")
ATTR = re.compile(r"\[\[[^\]]*\]\]\s*")


@dataclass
class Entity:
    kind: str                # file namespace class struct enum member function field alias constant macro
    name: str
    qualname: str
    header: str
    line: int
    signature: str = ""
    doc: str = ""
    trailing: str = ""
    access: str = "public"
    template: str = ""
    internal: bool = False
    group: str = ""          # the first line of the banner it sits under
    group_doc: str = ""      # that banner's whole text, on the group's first member
    covered: bool = False    # documented: its own doc, a trailing comment, its run's, its banner's
    run_doc: str = ""        # the doc it shares with the declaration above it
    value: str = ""
    static: bool = False
    virtual: bool = False
    deleted: bool = False
    end_line: int = 0
    branches: list = field(default_factory=list)   # macros: [(condition, body)]
    children: list = field(default_factory=list)
    parent: "Entity | None" = field(default=None, repr=False)

    def add(self, child: "Entity") -> "Entity":
        child.parent = self
        self.children.append(child)
        return child

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def public_children(self):
        return [c for c in self.children if not c.internal and not c.deleted]


class ParseError(Exception):
    def __init__(self, header, line, message):
        super().__init__(f"{header}:{line}: {message}")
        self.header, self.line, self.message = header, line, message


def strip_comment_line(s: str) -> str:
    s = s.strip()
    if s.startswith("//"):
        s = s[2:]
        if s.startswith(" "):
            s = s[1:]
    return s.rstrip()


def dedent_block(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def split_comment(line: str) -> tuple[str, str]:
    """The code of a line and its trailing // comment, outside literals."""
    masked = mask(line)
    i = masked.find("//")
    # mask() blanks comments; find the first position where the raw has //
    # and the masked has blanks.
    for m in re.finditer(r"//", line):
        k = m.start()
        if masked[k] == " " and (k == 0 or masked[k - 1] != "/"):
            if not _inside_literal(line, k):
                return line[:k], line[k + 2:].strip()
    del i
    return line, ""


def _inside_literal(line: str, k: int) -> bool:
    quote = None
    i = 0
    while i < k:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            if not (c == "'" and i > 0 and line[i - 1].isalnum() and i + 1 < len(line)
                    and line[i + 1].isalnum()):
                quote = c
        i += 1
    return quote is not None


def mask(text: str) -> str:
    """The text, same length, with comments and the insides of string and
    character literals turned into spaces (newlines kept), so that braces,
    parentheses and semicolons are only ever code."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in text[i:j]))
            i = j
        elif c == '"' or (c == "'" and not (i > 0 and text[i - 1].isalnum()
                                             and i + 1 < n and text[i + 1].isalnum())):
            if c == '"' and i > 0 and text[i - 1] == "R":   # raw string R"x(...)x"
                m = re.match(r'"([^(\s]*)\(', text[i:])
                if m:
                    end = text.find(")" + m.group(1) + '"', i)
                    end = n if end < 0 else end + len(m.group(1)) + 2
                    out.append('"' + "".join("\n" if ch == "\n" else " "
                                             for ch in text[i + 1:end - 1]) + '"')
                    i = end
                    continue
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(c + " " * (min(j, n) - i - 1) + (c if j < n and text[j] == c else ""))
            i = j + 1 if j < n and text[j] == c else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def collapse(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r"<\s+", "<", s)
    return s


def _matching(masked: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(start, len(masked)):
        if masked[i] == open_ch:
            depth += 1
        elif masked[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _angle_close(masked: str, start: int) -> int:
    depth = 0
    for i in range(start, len(masked)):
        if masked[i] == "<":
            depth += 1
        elif masked[i] == ">":
            depth -= 1
            if depth == 0:
                return i
    return -1


SCOPE_HEAD = re.compile(
    r"(?:template\s*<.*>\s*)?"
    r"(?:(namespace)(?:\s+([\w:]+))?"
    r"|(class|struct|union)\s+([\w:]+)(?:\s+final)?(?:\s*:\s*(.+))?"
    r"|(enum)(?:\s+(?:class|struct))?\s+(\w+)(?:\s*:\s*[\w:]+)?)\s*$", re.S)


class HeaderReader:
    def __init__(self, path: str, text: str):
        self.path = path
        self.text = text
        self.masked = mask(text)
        self.lines = text.split("\n")
        self.line_starts = [0]
        for m in re.finditer("\n", text):
            self.line_starts.append(m.end())
        self.banners = self._banners()
        self.root = Entity("file", path.rsplit("/", 1)[-1], "", path, 1)

    # -- positions --------------------------------------------------------------

    def line_of(self, pos: int) -> int:
        """1-based line number of an offset."""
        return bisect.bisect_right(self.line_starts, pos)

    def _banners(self):
        """(first_line, last_line, text) of every banner, 1-based inclusive."""
        out = []
        i = 0
        while i < len(self.lines):
            if BANNER.match(self.lines[i]):
                j = i + 1
                while j < len(self.lines) and not BANNER.match(self.lines[j]):
                    if not self.lines[j].strip().startswith("//"):
                        break
                    j += 1
                if j < len(self.lines) and BANNER.match(self.lines[j]):
                    body = [strip_comment_line(l) for l in self.lines[i + 1:j]]
                    out.append((i + 1, j + 1, dedent_block(body)))
                    i = j + 1
                    continue
            i += 1
        return out

    # -- the file block ---------------------------------------------------------

    def file_block(self) -> tuple[str, int]:
        for first, last, text in self.banners[:1]:
            before = [l.strip() for l in self.lines[:first - 1]]
            if all(b in ("", "#pragma once") for b in before):
                return text, last
        return "", 0

    # -- reading ----------------------------------------------------------------

    def read(self) -> Entity:
        doc, last = self.file_block()
        self.root.doc = doc
        start = self.line_starts[last] if last < len(self.line_starts) else len(self.text)
        self.scope(start, len(self.text), self.root, "file")
        return self.root

    def comment_above(self, line: int, floor: int) -> tuple[list[str], int | None]:
        """The `//` block that ends on line-1, and, if a banner ends right
        above that block (or right above the line), that banner's index."""
        block = []
        k = line - 1
        while k > floor:
            raw = self.lines[k - 1]
            if BANNER.match(raw):
                break
            s = raw.strip()
            if s.startswith("//"):
                block.insert(0, strip_comment_line(raw))
                k -= 1
                continue
            break
        banner = None
        for idx, (first, last, _text) in enumerate(self.banners):
            if last == k and first > floor:
                banner = idx
        return block, banner

    def scope(self, start: int, end: int, owner: Entity, kind: str):
        access = "private" if kind == "class" else "public"
        floor_line = self.line_of(start) - 1
        group, group_doc, group_banner = "", "", None
        prev_end_line = -10
        prev_entity = None
        run_doc = ""
        conditions: list[str] = []
        pos = start
        m = self.masked
        while pos < end:
            # Skip whitespace (comments are whitespace in the mask).
            while pos < end and m[pos].isspace():
                pos += 1
            if pos >= end:
                break
            line = self.line_of(pos)
            raw_line = self.lines[line - 1]

            # The current group: the last banner above this point, inside this scope.
            for idx, (first, last, text) in enumerate(self.banners):
                if first > floor_line and last < line and (group_banner is None or idx > group_banner):
                    group_banner = idx
                    group = text.split("\n", 1)[0].strip().rstrip(".")
                    group_doc = text

            if raw_line.lstrip().startswith("#"):
                pos = self.preprocessor(line, owner, conditions, floor_line)
                prev_end_line = -10
                continue

            am = re.match(r"(public|private|protected)\s*:", m[pos:pos + 12])
            if am and kind in ("class", "struct"):
                access = am.group(1)
                pos += am.end()
                prev_end_line = -10
                continue

            stmt_end, scope_body = self.statement_end(pos, end)
            text = self.text[pos:stmt_end]
            first_line = line
            last_line = self.line_of(stmt_end - 1)
            block, banner_idx = self.comment_above(first_line, floor_line)
            doc = dedent_block(block)
            under_banner = banner_idx is not None and self.banners[banner_idx][1] == first_line - 1 - len(block) \
                if block else banner_idx is not None
            in_run = not block and prev_end_line == first_line - 1
            if block:
                run_doc = doc
            elif not in_run:
                run_doc = ""
            trailing = split_comment(self.lines[last_line - 1])[1] if scope_body is None else ""

            ent = self.declaration(text, first_line, owner, access, trailing, scope_body, kind)
            if ent is not None:
                ent.end_line = last_line
                ent.group = group
                if ent.kind in ("class", "struct", "enum") and banner_idx is not None and not block:
                    # A banner directly above a type is the type's doc.
                    ent.doc = self.banners[banner_idx][2]
                    if group_banner == banner_idx:
                        group, group_doc = "", ""
                else:
                    ent.doc = doc
                    if under_banner and group_doc and not block:
                        ent.group_doc = group_doc
                ent.run_doc = run_doc if in_run else ""
                ent.covered = bool(ent.doc or ent.trailing or ent.run_doc or
                                   (under_banner and group_doc) or ent.kind == "namespace")
                if in_run and prev_entity is not None and not ent.covered:
                    ent.covered = prev_entity.covered
                prev_entity = ent
            prev_end_line = last_line
            pos = stmt_end

    def statement_end(self, pos: int, end: int) -> tuple[int, tuple[int, int] | None]:
        """Where a statement ends, and the inside of its braces when it opens
        a scope (namespace, class, struct, union, enum)."""
        m = self.masked
        depth = 0
        i = pos
        while i < end:
            c = m[i]
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            elif c == "{" and depth == 0:
                head = ATTR.sub("", m[pos:i]).strip()
                close = _matching(m, i, "{", "}")
                if close < 0:
                    raise ParseError(self.path, self.line_of(i), "an unclosed {")
                if SCOPE_HEAD.match(head):
                    after = close + 1
                    sm = re.match(r"\s*;", m[after:])
                    return (after + sm.end() if sm else after), (i + 1, close)
                if _is_function_head(head):
                    after = close + 1
                    sm = re.match(r"\s*;", m[after:])
                    return (after + sm.end() if sm else after), None
                i = close + 1          # an initializer: the statement goes on to its ;
                continue
            elif c == ";" and depth == 0:
                return i + 1, None
            i += 1
        raise ParseError(self.path, self.line_of(pos), "a declaration that never ends")

    def preprocessor(self, line: int, owner: Entity, conditions: list[str], floor: int) -> int:
        k = line - 1
        text = self.lines[k].strip()
        while text.endswith("\\") and k + 1 < len(self.lines):
            k += 1
            text = text[:-1].rstrip() + "\n" + self.lines[k].strip()
        word = re.match(r"#\s*(\w*)", text).group(1)
        if word in ("if", "ifdef", "ifndef"):
            conditions.append(text.split("\n")[0])
        elif word in ("elif", "else"):
            if conditions:
                conditions[-1] = text.split("\n")[0]
        elif word == "endif":
            if conditions:
                conditions.pop()
        elif word == "define":
            dm = re.match(r"#\s*define\s+(\w+)(\([^)]*\))?[ \t]*(.*)", text, re.S)
            name, params, body = dm.group(1), dm.group(2) or "", dm.group(3)
            block, _banner = self.comment_above(line, floor)
            existing = next((c for c in owner.children if c.kind == "macro" and c.name == name), None)
            if existing is None:
                existing = owner.add(Entity("macro", name, name, self.path, line,
                                            signature=f"#define {name}{params}"))
            if not existing.doc and block:
                existing.doc = dedent_block(block)
            existing.branches.append((conditions[-1] if conditions else "", body.strip()))
            existing.covered = bool(existing.doc)
            existing.end_line = k + 1
        return self.line_starts[k + 1] if k + 1 < len(self.line_starts) else len(self.text)

    def declaration(self, text, line, owner, access, trailing, scope_body, scope_kind):
        masked = mask(text)
        clean = ATTR.sub("", text).strip()
        cmasked = ATTR.sub("", masked).strip()
        template = ""
        tm = re.match(r"template\s*<", cmasked)
        if tm:
            close = _angle_close(cmasked, tm.end() - 1)
            template = collapse(clean[:close + 1])
            clean, cmasked = clean[close + 1:].strip(), cmasked[close + 1:].strip()
        if clean.startswith("friend "):
            clean, cmasked = clean[7:], cmasked[7:]

        if scope_body is not None:
            head = cmasked[:cmasked.find("{")].strip()
            sm = SCOPE_HEAD.match(head)
            body_start, body_end = scope_body
            if sm.group(1):                                   # namespace
                name = sm.group(2) or ""
                q = _join(owner.qualname, name) if name else owner.qualname
                ns = owner.add(Entity("namespace", name, q, self.path, line))
                ns.internal = owner.internal or not name or name.split("::")[-1] == "detail"
                self.scope(body_start, body_end, ns, "namespace")
                return ns
            if sm.group(3):                                   # class / struct / union
                kind = "class" if sm.group(3) == "class" else "struct"
                name = sm.group(4)
                base = collapse(sm.group(5)) if sm.group(5) else ""
                if "::" in name:
                    # `class Value::Ref {`: a nested class defined outside its
                    # class. It belongs to Value, where it was declared.
                    outer_name, name = name.rsplit("::", 1)
                    outer_q = _join(owner.qualname, outer_name)
                    outer = next((e for e in owner.walk() if e.qualname == outer_q), None)
                    if outer is None:
                        raise ParseError(self.path, line, f"{outer_q} is not declared above")
                    owner = outer
                ent = owner.add(Entity(kind, name, _join(owner.qualname, name), self.path, line,
                                       access=access, template=template,
                                       signature=f"{sm.group(3)} {name}" + (f" : {base}" if base else "")))
                ent.internal = owner.internal or access != "public"
                self.scope(body_start, body_end, ent, kind)
                return ent if access == "public" else None
            name = sm.group(7)                                # enum
            ent = owner.add(Entity("enum", name, _join(owner.qualname, name), self.path, line,
                                   access=access, signature=collapse(head)))
            ent.internal = owner.internal or access != "public"
            self.enum_members(body_start, body_end, ent)
            return ent if access == "public" else None

        if access != "public":
            return None
        if re.match(r"(class|struct|union|enum)(\s+class)?\s+[\w:]+\s*;", cmasked):
            return None                                       # a forward declaration
        if re.match(r"using\s+namespace\b", cmasked) or cmasked.startswith("static_assert"):
            return None
        um = re.match(r"using\s+(\w+)\s*=\s*(.*?)\s*;?\s*$", clean, re.S)
        if um:
            ent = owner.add(Entity("alias", um.group(1), _join(owner.qualname, um.group(1)),
                                   self.path, line, template=template,
                                   signature=collapse(f"using {um.group(1)} = {um.group(2)}")))
            ent.internal = owner.internal
            ent.trailing = trailing
            return ent

        par = _first_top_paren(cmasked)
        # operator= and operator== are names, not initialisers.
        eq = _first_top(re.sub(r"operator\s*[^\s(]+", lambda mo: " " * len(mo.group(0)), cmasked), "=")
        br = _first_top(cmasked, "{")
        if par >= 0 and (eq < 0 or par < eq) and (br < 0 or par < br):
            head = cmasked[:par].rstrip()
            om = re.search(r"\boperator\b(.*)$", head)
            if om:   # operator==, operator(), operator const T &
                rest = collapse(om.group(1))
                name = "operator" + (" " + rest if rest[:1].isalpha() else rest)
                if head.endswith("operator()") or (head.endswith("operator") and cmasked[par:par + 2] == "()"):
                    name = "operator()"
            else:
                nm = re.search(r"~?\w+$", head)
                if not nm:
                    raise ParseError(self.path, line, f"a function with no name: {collapse(clean)[:90]}")
                name = nm.group(0)
            close = _matching(cmasked, par, "(", ")")
            tail = cmasked[close + 1:]
            stop = len(tail)
            for marker in ("{", ";"):
                k = tail.find(marker)
                if k >= 0:
                    stop = min(stop, k)
            sig = collapse(clean[:close + 1 + stop])
            sig = re.sub(r"\s*=\s*0$", " = 0", sig)
            ent = owner.add(Entity("function", name, _join(owner.qualname, name), self.path, line,
                                   access=access, template=template, signature=sig))
            ent.static = bool(re.match(r"(inline\s+)?static\b", sig))
            ent.virtual = sig.startswith("virtual")
            # Deleted, and the special members left to the compiler, are not
            # something a game calls: they are hidden like deleted ones.
            ent.deleted = bool(re.search(r"=\s*(delete|default)\b", sig))
            ent.internal = owner.internal or name.startswith("detail_")
            ent.trailing = trailing
            return ent

        decl = clean.rstrip().rstrip(";").rstrip()
        dmask = mask(decl)
        cuts = [x for x in (_first_top(dmask, "="), _first_top(dmask, "{")) if x >= 0]
        cut = min(cuts) if cuts else len(decl)
        head = decl[:cut].strip()
        value = decl[cut:].strip()
        value = value[1:].strip() if value.startswith("=") else value
        nm = re.search(r"(\w+)\s*(\[[^\]]*\])?$", head)
        if not nm:
            raise ParseError(self.path, line, f"cannot read this declaration: {collapse(clean)[:90]}")
        name = nm.group(1)
        words = head.split()
        constant = ("constexpr" in words or ("const" in words and scope_kind in ("file", "namespace"))
                    or ("static" in words and "const" in words))
        ent = owner.add(Entity("constant" if constant else "field", name,
                               _join(owner.qualname, name), self.path, line, access=access,
                               template=template, signature=collapse(head), value=collapse(value)))
        ent.static = "static" in words
        ent.internal = owner.internal or name.startswith("detail_")
        ent.trailing = trailing
        return ent

    def enum_members(self, start: int, end: int, ent: Entity):
        first, last = self.line_of(start), self.line_of(end)
        pending: list[str] = []
        for ln in range(first, last + 1):
            raw = self.lines[ln - 1]
            lo = max(start, self.line_starts[ln - 1])
            hi = min(end, self.line_starts[ln] - 1 if ln < len(self.line_starts) else len(self.text))
            code_masked = self.masked[lo:hi]
            code = self.text[lo:hi]
            if not code_masked.strip():
                if raw.strip().startswith("//"):
                    pending.append(strip_comment_line(raw))
                else:
                    pending = []
                continue
            comment = split_comment(raw)[1]
            parts = [p for p in code_masked.split(",")]
            offset = 0
            for p in parts:
                piece = code[offset:offset + len(p)]
                offset += len(p) + 1
                piece_code = mask(piece).strip()
                if not piece_code:
                    continue
                mm = re.match(r"(\w+)\s*(?:=\s*(.+))?$", piece_code, re.S)
                if not mm:
                    raise ParseError(self.path, ln, f"cannot read the enum member {piece.strip()!r}")
                member = ent.add(Entity("member", mm.group(1), _join(ent.qualname, mm.group(1)),
                                        self.path, ln, value=collapse(piece.split("=", 1)[1])
                                        if "=" in piece else ""))
                member.doc = dedent_block(list(pending))
                member.trailing = comment
                member.internal = ent.internal
                member.covered = bool(member.doc or comment)
                member.end_line = ln
                pending = []


def _is_function_head(head: str) -> bool:
    h = head.rstrip()
    return bool(re.search(r"\)\s*(const|override|final|noexcept(\([^)]*\))?|&|&&|->\s*[\w:<>,\s*&]+|\s)*$", h)) \
        or bool(re.search(r"\)\s*:\s*\w+\s*[({]", h))       # a constructor's initialiser list


def _first_top(masked: str, ch: str) -> int:
    depth = 0
    angle = 0
    for i, c in enumerate(masked):
        if c in "([{":
            if c == ch and depth == 0:
                return i
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ch and depth == 0:
            return i
    return -1


def _first_top_paren(masked: str) -> int:
    """The first ( at the top level that is not inside a template's <>:
    `Handle<Object> follow;` has none, `RayHit raycast(Vector2 from)` has one."""
    depth = 0
    angle = 0
    for i, c in enumerate(masked):
        if c == "<":
            angle += 1
        elif c == ">" and angle:
            angle -= 1
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == "(" and depth == 0 and angle == 0:
            return i
    return -1


def _join(q: str, name: str) -> str:
    return f"{q}::{name}" if q else name


def read_header(path: str, text: str) -> Entity:
    return HeaderReader(path, text).read()
