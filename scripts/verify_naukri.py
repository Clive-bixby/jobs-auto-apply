"""Controlled Naukri-only submit verification.

Answers one question: does the Naukri apply flow actually confirm a submit?

It runs **one** Naukri search page and one collection pass. It keeps attempting
quick-apply listings until ``--max-jobs`` applications are **confirmed**, or it
runs out of ``--scan`` candidates. Detail-page rejections (non-quick-apply,
salary floor) cost a page visit but submit nothing, so they do not consume the
submit budget. It never purges state, never touches other platforms, and never
answers pending questions.

Usage (Chrome must be fully quit first):

    .venv\\Scripts\\python.exe scripts/verify_naukri.py
    .venv\\Scripts\\python.exe scripts/verify_naukri.py --max-jobs 2 --keywords "react developer"

Exit codes:
    0  at least one application confirmed and no confirm failures
    2  zero confirmed applications and at least one confirm failure (still broken)
    3  nothing eligible was attempted (inconclusive, not a submit failure)
    1  could not start (Chrome running, config missing, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from jobs_auto_apply.apply_filters import filter_pending_jobs  # noqa: E402
from jobs_auto_apply.browser import naukri_session  # noqa: E402
from jobs_auto_apply.chrome_profile import reset_chrome_lock_flag  # noqa: E402
from jobs_auto_apply.cli import _check_prerequisites  # noqa: E402
from jobs_auto_apply.config import load_config  # noqa: E402
from jobs_auto_apply.naukri.apply import apply_batch as naukri_apply_batch  # noqa: E402
from jobs_auto_apply.naukri.resume_sync import sync_naukri_resume_if_due  # noqa: E402
from jobs_auto_apply.naukri.search import (  # noqa: E402
    collect_naukri_srp_batch,
    go_to_search_page,
)
from jobs_auto_apply.utils import (  # noqa: E402
    load_applied_jobs,
    reconcile_applied_jobs,
    setup_logging,
)


async def _run_verification(config, scan_limit: int) -> int:
    """One SRP, one collection pass, submits capped by max_jobs_per_run.

    Mirrors the non-pipeline branch of ``cli._run_naukri``, but keeps the scan
    size independent of the apply cap and keeps walking past jobs that are
    rejected at the detail page (non-quick-apply, salary floor). Those cost a
    page visit but submit nothing, so they must not consume the submit budget —
    otherwise a 3-job test can end with 0 attempts and no verdict.
    """
    filters = config.naukri.filters
    max_apply = max(1, config.application.max_jobs_per_run)
    async with naukri_session(config) as (_, context, page):
        reconcile_applied_jobs(config.applied_jobs_path)
        await sync_naukri_resume_if_due(config, page=page)
        await go_to_search_page(page, filters)
        jobs = await collect_naukri_srp_batch(
            page,
            scan_limit,
            seen_job_ids=set(),
            quick_apply_only=filters.quick_apply_only,
            sort=filters.sort,
            max_job_age_days=filters.max_job_age_days,
            initial_scroll=True,
        )
        print(
            f"\nscanned {len(jobs)} quick-apply listing(s); "
            f"will attempt at most {scan_limit}, stop at {max_apply} confirmed submit(s)\n"
        )

        applied_ids = load_applied_jobs(config.applied_jobs_path)
        attempted = 0
        confirmed = 0
        while confirmed < max_apply and attempted < scan_limit:
            room = min(max_apply - confirmed, scan_limit - attempted)
            batch = filter_pending_jobs(jobs, applied_ids, room, config)
            if not batch:
                break
            attempted += len(batch)
            print(f"attempt {attempted}: " + "; ".join(f"{j.title} @ {j.company}" for j in batch))
            confirmed += await naukri_apply_batch(page, context, batch, config)
        return confirmed


def _chrome_process_count() -> int:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    return sum(1 for line in out.splitlines() if "chrome.exe" in line.lower())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--max-jobs", type=int, default=3, help="hard cap on confirmed applications (default 3)")
    parser.add_argument(
        "--scan",
        type=int,
        default=None,
        help="listings to inspect before the apply cap (default: 3 x --max-jobs)",
    )
    parser.add_argument("--keywords", default=None, help="override naukri.filters.keywords for this run")
    parser.add_argument("--force", action="store_true", help="run even if Chrome is open")
    return parser.parse_args()


def _recent_naukri_entries(path: Path, since: datetime) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    recent = []
    for entry in payload.get("history", []):
        if entry.get("source") != "naukri":
            continue
        raw = entry.get("applied_at") or ""
        try:
            when = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= since:
            recent.append(entry)
    return recent


def _log_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def main() -> int:
    args = _parse_args()
    config_path = args.config.resolve()

    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    chrome_count = _chrome_process_count()
    if chrome_count and not args.force:
        print(
            f"Chrome is running ({chrome_count} processes). The run reuses your real Chrome\n"
            "profile, so Chrome must be fully quit (including background/tray processes).\n"
            "Quit Chrome, then re-run. Use --force only if you know the profile is free."
        )
        return 1

    config = load_config(config_path)
    filters = config.naukri.filters

    # --- verification overrides: one SRP, one collection pass, hard apply cap -
    max_apply = max(1, args.max_jobs)
    scan_limit = max(max_apply, args.scan or max_apply * 3)
    config.application.max_jobs_per_run = max_apply
    config.application.pipeline_apply = False
    config.application.parallel_platforms = False
    config.application.dry_run = False
    config.application.require_review = False
    config.application.naukri_apply_workers = 1
    filters.max_pages = 1
    filters.search_urls = []
    filters.quick_apply_only = True
    if args.keywords:
        filters.keywords = args.keywords

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    log_path = config.base_dir / "data" / f"naukri-verify-{stamp}.log"
    setup_logging(log_path, verbose=False)
    reset_chrome_lock_flag()
    _check_prerequisites(config, require_resume=True)

    # The run appends to history; keep a copy so a bad verification can be undone.
    if config.applied_jobs_path.exists():
        backup = config.applied_jobs_path.with_suffix(f".json.bak-{stamp}")
        backup.write_bytes(config.applied_jobs_path.read_bytes())
        print(f"history backup: {backup}")

    started = datetime.now(timezone.utc)
    print(
        f"Naukri verification: keywords={filters.keywords!r} "
        f"scan={scan_limit} max_jobs={max_apply} quick_apply_only=True\n"
        f"log: {log_path}\n"
    )

    try:
        applied = asyncio.run(_run_verification(config, scan_limit))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface any startup/browser failure
        print(f"\nRun failed before a verdict: {type(exc).__name__}: {exc}")
        return 1

    recent = _recent_naukri_entries(config.applied_jobs_path, started)
    confirmed = [e for e in recent if e.get("status") == "applied"]
    abandoned = [e for e in recent if e.get("status") != "applied"]
    confirm_failures = [line for line in _log_lines(log_path) if "Could not confirm Naukri apply" in line]
    save_apply = [line for line in _log_lines(log_path) if "saveApply" in line]

    print("\n" + "=" * 62)
    print("NAUKRI SUBMIT VERDICT")
    print("=" * 62)
    print(f"reported applied this run : {applied}")
    print(f"history entries recorded  : {len(recent)}  (applied {len(confirmed)}, abandoned {len(abandoned)})")
    print(f"confirm failures in log   : {len(confirm_failures)}")
    for entry in confirmed:
        print(f"  OK  {entry.get('title')} @ {entry.get('company') or '-'}")
    for entry in abandoned:
        print(f"  XX  {entry.get('title')} @ {entry.get('company') or '-'} — {entry.get('reason') or 'unknown'}")
    for line in confirm_failures[:5]:
        print(f"  log: {line.strip()}")
    for line in save_apply[:5]:
        print(f"  log: {line.strip()}")

    if confirmed and not confirm_failures:
        print("\nRESULT: submit path confirmed. Safe to restore Naukri SRPs.")
        return 0
    if not confirmed and confirm_failures:
        print("\nRESULT: submit path still broken — do not spend full runs on Naukri yet.")
        return 2
    if not confirmed and not confirm_failures:
        print("\nRESULT: inconclusive — nothing eligible was attempted (gate/supply, not submit).")
        return 3
    print("\nRESULT: partial — some submits confirmed, some did not. Inspect the log above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
