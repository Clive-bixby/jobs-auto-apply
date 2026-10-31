"""Open the persistent automation profile so you can log in manually.

Usage:
    .venv\\Scripts\\python.exe scripts\\open_login_browser.py
    .venv\\Scripts\\python.exe scripts\\open_login_browser.py --seconds 3

Opens the dedicated profile visibly with one tab per job site, then waits until
you close the browser window. Every cookie/localStorage entry you create is kept
in browser-data/job-search-profile and reused by the automation afterwards.
Nothing is submitted and no credentials are read or printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobs_auto_apply.chrome_profile import (  # noqa: E402
    assert_chrome_profile_available,
    resolve_chrome_profile_dir,
)
from jobs_auto_apply.config import load_config  # noqa: E402

SITES = [
    ("Naukri", "https://www.naukri.com/nlogin/login"),
    ("Wellfound", "https://wellfound.com/login"),
    ("Instahyre", "https://www.instahyre.com/login/"),
    ("Uplers", "https://www.uplers.com/talent/login"),
    ("Hirist", "https://www.hirist.tech/"),
]


async def main(seconds: int) -> int:
    from playwright.async_api import async_playwright

    config = load_config(ROOT / "config.yaml")
    profile_dir = resolve_chrome_profile_dir(config)
    assert_chrome_profile_available(profile_dir)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel=config.browser.chrome_channel or "chrome",
            headless=False,
            args=["--no-first-run", "--no-default-browser-check", "--start-maximized"],
        )
        try:
            first = context.pages[0] if context.pages else await context.new_page()
            await first.goto(SITES[0][1])
            for _, url in SITES[1:]:
                page = await context.new_page()
                await page.goto(url)

            print(f"\nProfile: {profile_dir}")
            print("Log in to each tab, then close the browser window to save the session.")
            print("Nothing is submitted and no credentials are stored or printed.\n")

            if seconds:
                await asyncio.sleep(seconds)
            else:
                closed = asyncio.Event()
                context.on("close", lambda _: closed.set())
                await closed.wait()
        finally:
            await context.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seconds",
        type=int,
        default=0,
        help="auto-close after N seconds (0 = wait until you close the window)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.seconds)))
