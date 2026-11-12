# rmp-docs

The documentation site of [raylib_multiplatform](https://github.com/omardev29/raylib_multiplatform),
built from plain HTML fragments and from the framework's own headers, by one standard-library
Python script, and checked against the framework at the commit in `FRAMEWORK_REF`.

```bash
python3 tools/build.py build      # writes _site/ and runs every gate
python3 tools/build.py serve      # the same, then serves it on localhost:8040
python3 tools/build.py gates      # what each gate checks
python3 -m unittest discover -s tests   # the property tests need hypothesis (pip install
                                        # hypothesis); RMP_REQUIRE_HYPOTHESIS=1 makes them required
bash tests/mutation/run.sh run          # mutation testing of tools/rmpdocs, in the framework's
                                        # build image (RMP_FRAMEWORK must have tools/mutation_report.py)
```

The framework is read from `--framework PATH`, `$RMP_FRAMEWORK`, or `../raylib_multiplatform`.

| Folder | Holds |
| --- | --- |
| `content/` | one HTML fragment per page, after a front-matter comment |
| `templates/` | what goes around every page |
| `assets/` | the stylesheets, the scripts, the self-hosted fonts |
| `tools/` | `build.py` and its modules |
| `tests/` | the unit tests, a red and a green fixture for every gate, the browser checks |

## Pictures

A page shows only pictures the build makes from code, so none of them can go stale
(`tools/rmpdocs/shots.py`, the `pictures` gate):

```html
<!-- a golden of the framework's e2e scripts, tests/e2e/golden/ui/01_menu/options.png at FRAMEWORK_REF -->
<figure class="shot"><img src="/shots/e2e/ui/01_menu/options.png" alt="What it shows"
  width="800" height="450"></figure>

<!-- the tutorial's game after a page, made by --tier project; data-scene/data-header start it in
     a scene the tutorial wrote, for the picture only -->
<figure class="shot"><img src="/shots/tutorial/my_game/a-player.png" alt="What it shows"
  width="800" height="450" data-scene="GameScene" data-header="scenes/game.h"></figure>
```

Every picture has its alt text. A PNG kept in `content/`, or any other image address, is refused.
The tutorial's pictures exist only in a `--tier project` build (the one the site deploys).
