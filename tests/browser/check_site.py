"""The built site in a real browser: what static checks cannot see.

    python3 tests/browser/check_site.py _site SHOTS_DIR

  - every page loads with no console error and no failed request;
  - no page scrolls sideways on a 360 px phone, in either theme;
  - the theme switch cycles auto -> light -> dark and is remembered;
  - search opens with "/", finds a name, and Enter goes to it;
  - screenshots of the key pages, desktop and phone, light and dark, for a
    person to look at -- which is how layout bugs are actually found.

Exit 1 with every failure listed, 0 when the site holds.
"""

import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

KEY_PAGES = ["index.html", "manual/core/scenes.html", "reference/classes/rmp-Camera.html",
             "reference/namespaces/rmp-ui.html", "getting-started/index.html"]


def png_ratio(data: bytes) -> float:
    """The fraction of pixels that differ from the most common colour, read
    from a PNG with nothing but zlib: what says a frame was drawn."""
    import struct
    import zlib
    pos = 8
    width = height = 0
    idat = b""
    channels = 4
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", chunk[:10])
            channels = {2: 3, 6: 4, 0: 1, 4: 2}[colour]
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * channels
    rows = []
    prev = bytearray(stride)
    i = 0
    for _ in range(height):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = prev[x]
            c = prev[x - channels] if x >= channels else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    counts = {}
    for row in rows:
        for x in range(0, stride, channels):
            px = row[x:x + 3]
            counts[px] = counts.get(px, 0) + 1
    total = width * height
    return 1 - max(counts.values()) / total if total else 0.0


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main(site: Path, shots: Path) -> int:
    shots.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(Quiet, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    pages = sorted(p.relative_to(site).as_posix() for p in site.rglob("*.html"))
    failures = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        def visit(url, width, height, theme):
            ctx = browser.new_context(viewport={"width": width, "height": height})
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"script: {e}"))
            page.on("requestfailed", lambda r: errors.append(f"request failed: {r.url}"))
            page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None)
            page.goto(f"{base}{url}?theme={theme}")
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            return ctx, page, errors

        for url in pages:
            for theme in ("light", "dark"):
                ctx, page, errors = visit(url, 360, 760, theme)
                over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if over > 0:
                    failures.append(f"{url} ({theme}, 360 px): scrolls sideways by {over} px")
                failures += [f"{url}: {e}" for e in errors]
                ctx.close()

        for url in KEY_PAGES:
            for theme in ("light", "dark"):
                for name, w, h in (("desktop", 1366, 900), ("phone", 390, 844)):
                    ctx, page, errors = visit(url, w, h, theme)
                    stem = url.replace("/", "_").removesuffix(".html")
                    page.screenshot(path=str(shots / f"{stem}-{name}-{theme}.png"))
                    failures += [f"{url}: {e}" for e in errors]
                    ctx.close()

        # Every example that has a player: Play, it boots with every asset
        # loaded, and it draws.
        players = sorted(p.relative_to(site).as_posix() for p in (site / "examples").rglob("*.html")
                         if 'class="player"' in p.read_text(encoding="utf-8"))
        for url in players:
            ctx = browser.new_context(viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            said = []
            page.on("console", lambda m: said.append(m.text))
            page.goto(f"{base}{url}")
            page.click(".play-button")
            for _ in range(60):     # up to 15 s: the .wasm and .data have to arrive
                if any("RAY_TEST_BOOT_OK" in s for s in said):
                    break
                page.wait_for_timeout(250)
            boot = next((s for s in said if "RAY_TEST_BOOT_OK" in s), "")
            if not boot:
                failures.append(f"{url}: Play did not boot the example (no RAY_TEST_BOOT_OK); "
                                f"the console said: {said[:6]}")
            elif "assets_failed=0" not in boot:
                failures.append(f"{url}: the example booted with assets missing: {boot}")
            page.wait_for_timeout(1500)
            shot = page.frame_locator(".player iframe").locator("canvas").screenshot()
            ratio = png_ratio(shot)
            if ratio < 0.01:
                failures.append(f"{url}: the example's canvas is blank (ratio {ratio:.4f})")
            stem = url.replace("/", "_").removesuffix(".html")
            (shots / f"played-{stem}.png").write_bytes(shot)
            ctx.close()
        print(f"  played {len(players)} examples in their pages")

        # The theme switch, and that the choice survives a reload.
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, color_scheme="light")
        page = ctx.new_page()
        page.goto(f"{base}manual/core/scenes.html")
        seen = []
        for _ in range(3):
            page.click(".theme-toggle")
            seen.append(page.evaluate("document.documentElement.getAttribute('data-theme') || 'auto'"))
        if seen != ["light", "dark", "auto"]:
            failures.append(f"theme switch cycled {seen}, not light, dark, auto")
        page.click(".theme-toggle")
        page.reload()
        if page.evaluate("document.documentElement.getAttribute('data-theme')") != "light":
            failures.append("the theme chosen is not remembered across a reload")
        dark_bg = None
        page.click(".theme-toggle")
        dark_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        if dark_bg != "rgb(18, 18, 22)":
            failures.append(f"the dark theme's background is {dark_bg}, not #121216")

        # Search: open it with "/", find a name, go there with Enter.
        page.goto(f"{base}manual/core/scenes.html")
        page.keyboard.press("/")
        page.wait_for_selector(".search-dialog input")
        page.fill(".search-dialog input", "spawn")
        page.wait_for_selector(".search-results [role=option]")
        first = page.inner_text(".search-results [role=option]")
        if "rmp::Scene::spawn" not in first:
            failures.append(f"searching 'spawn' put {first!r} first, not rmp::Scene::spawn")
        page.keyboard.press("Enter")
        try:
            page.wait_for_url("**/reference/classes/rmp-Scene.html#spawn", timeout=5000)
        except Exception:
            failures.append(f"Enter on the first result went to {page.url}")
        ctx.close()
        browser.close()
    server.shutdown()

    for f in failures:
        print(f"FAIL  {f}")
    if failures:
        print(f"FAIL: {len(failures)} problem(s) in the browser")
        return 1
    print(f"PASS: {len(pages)} pages in Chromium, at 360 px in both themes; theme switch; search")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
