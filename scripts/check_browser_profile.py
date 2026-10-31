"""Verify the automation browser profile persists sessions across restarts.

Usage:  .venv\\Scripts\\python.exe scripts\\check_browser_profile.py [--visible]

Writes a marker cookie + localStorage entry, closes the browser, reopens the
same profile, and checks both are still there. Makes no network requests to job
sites and submits nothing.
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
    uses_dedicated_profile,
)
from jobs_auto_apply.config import load_config  # noqa: E402

MARKER_URL = "https://example.com"
COOKIE_NAME = "persist_check"


async def _open(profile_dir: Path, visible: bool, write: bool) -> dict[str, str | None]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=not visible,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(MARKER_URL)
            if write:
                import time

                await context.add_cookies(
                    [
                        {
                            "name": COOKIE_NAME,
                            "value": "1",
                            "url": MARKER_URL,
                            # Persistent cookie: a session cookie (no expires) is
                            # dropped on browser exit by design, which would make
                            # this check fail for a perfectly good profile.
                            "expires": time.time() + 30 * 24 * 3600,
                        }
                    ]
                )
                await page.evaluate("() => localStorage.setItem('persist_check', '1')")
                await page.wait_for_timeout(500)
                state = {"cookie": "1", "localStorage": "1"}
            else:
                state = {
                    "cookie": await page.evaluate(
                        f"() => document.cookie.includes('{COOKIE_NAME}=')"
                    ),
                    "localStorage": await page.evaluate(
                        "() => localStorage.getItem('persist_check')"
                    ),
                }
            return {k: str(v) for k, v in state.items()}
        finally:
            await context.close()


async def main(visible: bool) -> int:
    config = load_config(ROOT / "config.yaml")
    profile_dir = resolve_chrome_profile_dir(config)

    print(f"resolved profile : {profile_dir}")
    print(f"dedicated        : {uses_dedicated_profile(config)}")
    print(f"user_data_dir    : {config.browser.chrome_user_data_dir}")
    print(f"headless         : {config.browser.headless}")

    assert_chrome_profile_available(profile_dir)

    print("\npass 1: writing marker cookie + localStorage ...")
    await _open(profile_dir, visible, write=True)

    print("pass 2: reopening the same profile ...")
    state = await _open(profile_dir, visible, write=False)
    print(f"  cookie persisted      : {state['cookie']}")
    print(f"  localStorage persisted: {state['localStorage']}")

    ok = state["cookie"] == "True" and state["localStorage"] == "1"
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} — profile reused at {profile_dir}")
    if not ok:
        print("Login data did not survive a restart; do not rely on this profile yet.")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--visible", action="store_true", help="show the browser window")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.visible)))
