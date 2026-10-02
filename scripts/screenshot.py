#!/usr/bin/env python3
"""Capture README screenshots of the running dashboard.

Usage::

    pip install playwright && playwright install chromium
    # start the app first (make run), then:
    python scripts/screenshot.py                    # -> docs/screenshots/*.png
    python scripts/screenshot.py --base-url http://localhost:8000

The script logs in with the demo account, walks the tabs and writes one PNG per
view at 1440x900 (plus a mobile viewport). It is intentionally *not* part of the
test suite: browsers are heavy, and screenshots are a documentation concern.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

TABS = [
    ("overview", "01-dashboard"),
    ("transactions", "02-transactions"),
    ("budgets", "03-budgets"),
    ("goals", "04-goals"),
    ("recurring", "05-recurring"),
    ("data", "06-import-export"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", default="demo@pfm.app")
    parser.add_argument("--password", default="demo1234")
    parser.add_argument("--theme", default="dark", choices=["dark", "light"])
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is not installed.\n"
            "  pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.goto(f"{args.base_url}/app", wait_until="networkidle")

        page.fill("#login-email", args.email)
        page.fill("#login-password", args.password)
        page.click("#login-form button[type=submit]")
        page.wait_for_selector("#kpis .kpi", timeout=15_000)

        page.evaluate("(theme) => localStorage.setItem('pfm_theme', theme)", args.theme)
        page.reload(wait_until="networkidle")
        page.wait_for_selector("#kpis .kpi", timeout=15_000)

        for tab, filename in TABS:
            page.click(f'[data-tab="{tab}"]')
            page.wait_for_timeout(600)
            target = OUT_DIR / f"{filename}.png"
            page.screenshot(path=str(target), full_page=True)
            print(f"wrote {target.relative_to(OUT_DIR.parent.parent)}")

        mobile = browser.new_page(viewport={"width": 414, "height": 896}, device_scale_factor=2)
        mobile.goto(f"{args.base_url}/app", wait_until="networkidle")
        mobile.fill("#login-email", args.email)
        mobile.fill("#login-password", args.password)
        mobile.click("#login-form button[type=submit]")
        mobile.wait_for_selector("#kpis .kpi", timeout=15_000)
        target = OUT_DIR / "07-mobile.png"
        mobile.screenshot(path=str(target), full_page=True)
        print(f"wrote {target.relative_to(OUT_DIR.parent.parent)}")

        browser.close()

    print(
        "\nDone. Reference them from the README, e.g. "
        "![dashboard](docs/screenshots/01-dashboard.png)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
