"""Manual application entries — jobs you applied to outside this bot.

They live in the *same* ledger the bot already owns (``data/applied_jobs.json``),
so the dashboard, the CSV/HTML export and the bot's own duplicate checks all see
one history. No second database and no new file format.

Each entry carries ``manual: true`` and a ``manual:<slug>-<id>`` job key, which
can never collide with a real ``<platform>:<job_id>`` key, so adding one can
never cause the bot to skip a job it actually found.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils import _applied_jobs_lock, _load_applied_payload, save_applied_job

PLATFORM_CHOICES = (
    "manual",
    "naukri",
    "hirist",
    "instahyre",
    "wellfound",
    "uplers",
    "linkedin",
    "indeed",
    "other",
)


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return text[:40] or "job"


def normalize_applied_at(value: str | None) -> str:
    """Return an aware UTC ISO timestamp.

    ``applied_report`` subtracts these from ``datetime.now().astimezone()``, so a
    naive value would raise; a date-only value is treated as local midnight.
    """
    raw = (value or "").strip()
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return datetime.now(timezone.utc).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).isoformat()


def add_manual_application(
    applied_jobs_path: Path,
    *,
    title: str,
    company: str = "",
    url: str = "",
    platform: str = "manual",
    applied_at: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Append a manual row to the bot's applied-jobs ledger."""
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("a job title is required")

    chosen = (platform or "manual").strip().lower()
    if chosen not in PLATFORM_CHOICES:
        chosen = "other"

    key = f"manual:{_slug(company or clean_title)}-{secrets.token_hex(3)}"
    meta: dict[str, Any] = {
        # save_applied_job writes these after job_key/status, so applied_at here
        # overrides its "now" default — letting you back-date an entry.
        "applied_at": normalize_applied_at(applied_at),
        "source": chosen,
        "title": clean_title,
        "company": company.strip(),
        "url": url.strip(),
        "reason": note.strip(),
        "manual": True,
    }
    save_applied_job(applied_jobs_path, key, meta, status="applied")
    return {"job_key": key, **meta, "status": "applied"}


def delete_manual_application(applied_jobs_path: Path, key: str) -> bool:
    """Remove a manual entry. Bot-recorded rows are never touched."""
    if not key.startswith("manual:"):
        return False

    with _applied_jobs_lock:
        payload = _load_applied_payload(applied_jobs_path)
        history = payload.get("history") or []
        kept = [
            entry
            for entry in history
            if not (
                isinstance(entry, dict)
                and str(entry.get("job_key", "")) == key
                and entry.get("manual")
            )
        ]
        if len(kept) == len(history):
            return False
        payload["history"] = kept
        payload["applied"] = sorted(
            {
                str(entry.get("job_key"))
                for entry in kept
                if isinstance(entry, dict)
                and entry.get("job_key")
                and str(entry.get("status", "")).strip() in ("applied", "deferred", "abandoned")
            }
        )
        applied_jobs_path.parent.mkdir(parents=True, exist_ok=True)
        applied_jobs_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True
