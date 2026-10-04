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

KEY_PAGES = ["index.html", "manual/core/scenes.html", "reference/rmp-Camera.html",
             "getting-started/index.html"]


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
            page.wait_for_url("**/reference/rmp-Scene.html#spawn", timeout=5000)
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
