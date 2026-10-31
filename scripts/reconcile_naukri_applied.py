"""Reconcile Naukri "technical failures" against the live site.

Apply confirmation can race Naukri's page render, so an application that did go
through is sometimes recorded as a technical failure. This visits each failed
job's detail page and, when `.already-applied` is present, records the job as
applied and clears the false failure.

Usage (Chrome must be fully closed):
    .venv/Scripts/python.exe scripts/reconcile_naukri_applied.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobs_auto_apply.chrome_profile import resolve_chrome_profile_dir  # noqa: E402
from jobs_auto_apply.config import load_config  # noqa: E402
from jobs_auto_apply.technical_failures import (  # noqa: E402
    clear_technical_failure,
    technical_failures_path,
)
from jobs_auto_apply.utils import save_applied_job  # noqa: E402

_APPLIED_JS = "() => !!document.querySelector('.already-applied')"


def _naukri_failures(base_dir: Path) -> list[tuple[str, dict]]:
    path = technical_failures_path(base_dir)
    if not path.exists():
        return []
    failures = json.loads(path.read_text(encoding="utf-8")).get("failures", {})
    return [(key, entry) for key, entry in failures.items() if entry.get("source") == "naukri"]


async def _run(args: argparse.Namespace) -> int:
    from playwright.async_api import async_playwright

    config = load_config(Path(args.config))
    failures = _naukri_failures(config.base_dir)
    if args.limit and args.limit > 0:
        failures = sorted(failures, key=lambda kv: kv[1].get("last_seen", ""), reverse=True)[: args.limit]
    if not failures:
        print("No Naukri technical failures to reconcile.")
        return 0

    profile = resolve_chrome_profile_dir(config)
    print(f"Checking {len(failures)} Naukri failure(s) on the live site...")
    applied: list[str] = []
    still_failing: list[str] = []

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            # Naukri serves "Access Denied" to headless browsers, so always headed.
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            for key, entry in failures:
                url = entry.get("url") or ""
                label = f"{entry.get('title')} @ {entry.get('company')}"
                if not url:
                    still_failing.append(label)
                    continue
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(4000)
                if await page.evaluate(_APPLIED_JS):
                    save_applied_job(
                        config.applied_jobs_path,
                        key,
                        {"source": "naukri", "title": entry.get("title", ""), "url": url},
                        status="applied",
                    )
                    clear_technical_failure(config.base_dir, key)
                    applied.append(label)
                else:
                    still_failing.append(label)
        finally:
            await ctx.close()

    print(f"\nApplied on site: {len(applied)}")
    for label in applied:
        print(f"  + {label}")
    if still_failing:
        print(f"\nStill not applied: {len(still_failing)}")
        for label in still_failing:
            print(f"  - {label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="check only the N most recently seen failures (0 = all)",
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
