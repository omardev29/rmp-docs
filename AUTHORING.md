# Writing a page

The rule above every other: **a page may not say anything that is not true of the framework at
`FRAMEWORK_REF`.** Everything a machine can check about a page is checked by `tools/build.py`;
everything it cannot, you check by reading the framework's source before you write the sentence.
If you are not sure, read more source, or leave the sentence out.

```bash
python3 tools/build.py check                  # every gate
python3 tools/build.py check --tier compile   # and every C/C++ block compiled
python3 tools/build.py serve                  # http://localhost:8040
```

The framework is read from `../raylib_multiplatform`. The compile tier needs its `build/lint`:
`(cd ../raylib_multiplatform && python3 tools/configure.py && cmake --preset lint)`.

## A page is a fragment

`content/<section>/[<group>/]<page>.html` — the article only, no `<html>`, no layout. It starts
with a front-matter comment:

```html
<!--
title: Scenes
description: One sentence, ending with a full stop: the tab, the search result, the preview.
order: 20
-->
<h1>Scenes</h1>
```

- `order` sorts the page in its group's sidebar. A folder is a group when it has an `index.html`.
- One `<h1>`. `<h2>`/`<h3>` build "On this page"; give them short, specific text.
- Well-formed HTML: every element closed, in order. The `html` gate refuses anything else.
- Links inside the site are root-relative: `<a href="/manual/core/scenes.html#the-hooks">`.
  The build makes them relative; the `links` gate checks the page and the anchor exist.
- A link to a reference entry: `<a href="ref:rmp::Scene::change">` — the `names` gate checks it.
- A link to a framework file at the documented commit: `<a href="fw:src/rmp/app.cpp#L40-L60">`.
- Outside links only to hosts in `site.toml [links] allow`, https only.
- `` `backticks` `` in text become `<code>`. Code-shaped names are checked: `rmp::...`,
  `RMP_...`, raylib/rlgl/Clay functions written as `Name()`, `KEY_...` and friends must exist.
- A path written as code (`src/main.cpp`, `examples/games/01_pong`) must exist in the framework
  or in a game `rmp new` makes.

## Numbers and lists are the framework's

Never type a count of targets, examples, games, headers, behaviors, families: write
`{{count:targets}}`, `{{count:examples}}`, `{{count:games}}`, `{{count:headers}}`,
`{{count:families}}`, `{{list:targets}}`. The `counts` gate refuses a digit or a number word
next to those nouns. A table of every target: `<div data-generated="targets-table"></div>`.

## Code

Every block says its language: `<pre data-lang="cpp">` — `cpp`, `c`, `toml`, `shell`,
`powershell`, `cmake`, `json`, `yaml`, `text`. Escape `<`, `>` and `&` inside it.

**Every C and C++ block is compiled** against the framework (`--tier compile`). It says how:

| Attribute | The block is |
| --- | --- |
| `data-harness="file"` | a whole translation unit, includes and all |
| `data-harness="toplevel"` | at namespace scope, after every `rmp/` header |
| `data-harness="function"` | statements inside a function |
| `data-harness="scene"` | statements inside a method of an `rmp::Scene` subclass (`spawn`, `camera`, `map` in scope) |
| `data-harness="object"` | statements inside a method of an `rmp::Object` subclass (`position`, `velocity`, `add<B>()` in scope) |
| `data-harness="members"` | members of a scene class: overrides and fields |
| `data-harness="c99"` | plain C with `<raylib.h>` |
| `data-include="examples/.../main.cpp" data-region="name"` | quoted from a real file, between `// doc-region: name` and `// doc-region-end: name` |

`data-given="void play(); struct GameScene : rmp::Scene {};"` adds declarations the block uses
and does not show. Keep them small and honest: they stand for the reader's own code.

A block that shows a mistake on purpose: `data-expect="error" data-error="no matching function"`
— it must fail, and the compiler must say those words. Pick words GCC and Clang both print.

Quote a long piece of a real example with `data-include` rather than retyping it: the
framework's CI builds and boots that file.

**A tutorial is a real game.** A block with `data-project="my_game" data-file="src/scenes/play.cpp"`
is that whole file of the tutorial's game at that page; the next page that gives the same file
replaces it. A `toml` block with `data-file="raylib_multiplatform.toml"` holds only the keys it
sets, under their `[section]`. A file the reader copies from the framework (art, a sound) is a
shell block with `data-project`, `data-file="resources/hit.wav"` and
`data-copy-from="examples/games/01_pong/resources/hit.wav"`. `--tier project` makes the game with
`rmp new`, and after each page — in sidebar order — applies its files, builds the game for the
software renderer and boots it: it has to load every asset, draw, and exit cleanly. While the game
has tests in `tests/game/`, they have to pass too, under `rmp test unit`: a page that changes what
the test `rmp new` wrote tests gives its own version of that file.

**Every `toml` block is run through `configure.py --check --config`**: it has to be accepted. A
block that shows a refusal is `data-expect="reject"`; the build prints configure.py's real
message under it — never type the error yourself. A toml block that is not
`raylib_multiplatform.toml` is `data-config="no" data-reason="..."`.

**Every `rmp` command** in a shell block or in code is checked against `rmp help --json`, every
`cmake --preset` against `CMakePresets.json`.

**A message the framework prints**, quoted, goes in `<samp>`: the `diagnostics` gate requires
it to match a string the framework really prints (`…` for the parts you leave out).

**A sentence about how the framework works inside** can be pinned to its source:
`<p data-fw-grep="src/rmp/app.cpp::rmp::scenes::detail::draw\(\)">`. If the code changes, the
gate tells whoever bumps `FRAMEWORK_REF`. Pin the claim WITH its context: a regex that
names only a call still matches after the call moves to another function, and the page goes on
saying where it is. Span from the enclosing function's head to the line you mean
(`void frame\(float delta\) \{[^}]*begin_frame`), so moving it is a change the gate sees.

No raster images. Diagrams are inline SVG whose colours are CSS variables (`var(--text)`,
`var(--accent)`, `var(--border)`, `var(--bg-sunken)`), so they follow the theme.

## Callouts

```html
<aside class="callout"><span class="callout-title">Note</span><p>…</p></aside>
<aside class="callout warning"><span class="callout-title">Careful</span><p>…</p></aside>
<aside class="callout danger"><span class="callout-title">Never</span><p>…</p></aside>
```

## How it reads

- English, plain and exact. Say what a thing is for and why it works that way, in that order.
  A reason is worth more than an adjective.
- The reader is someone making a game: start from what they want to do, then the code, then
  the detail. Short paragraphs; one idea each.
- Present tense, about the framework as it is. No history ("used to", "phase N", "now"), no
  promises about later.
- Name things exactly as the code does: `rmp::Scene::change`, `[window] vsync`, `rmp test`.
- Show the smallest code that does the thing, and only code that compiles.
- Never claim a number, a default, a platform behaviour or an error message you have not read
  in the source at `FRAMEWORK_REF`.
