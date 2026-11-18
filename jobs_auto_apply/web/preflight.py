"""Prerequisites a browser run needs, surfaced before anything is launched.

The bot drives either the real Chrome profile or a dedicated automation profile.
With the real profile, Chrome must be fully closed, so a run started while it is
open dies immediately at ``ChromeProfileLockedError``. Checking up front turns
that into an actionable message in the dashboard instead of a failed run whose
only explanation is a traceback in ``data/run.log``.

This module only *reports*; it never closes Chrome or changes config.
"""

from __future__ import annotations

import time
from typing import Any

from ..chrome_profile import is_chrome_process_running, resolve_chrome_profile_dir, uses_dedicated_profile

# `tasklist` is a subprocess; the dashboard polls /api/status every few seconds,
# so memoise the probe briefly.
_CHROME_TTL_SECONDS = 3.0
_chrome_cache: tuple[float, bool] | None = None


def chrome_running() -> bool:
    global _chrome_cache
    now = time.monotonic()
    if _chrome_cache is not None and now - _chrome_cache[0] < _CHROME_TTL_SECONDS:
        return _chrome_cache[1]
    running = is_chrome_process_running()
    _chrome_cache = (now, running)
    return running


def reset_cache() -> None:
    global _chrome_cache
    _chrome_cache = None


def blockers(config: Any) -> list[dict[str, Any]]:
    """Return every prerequisite problem, each tagged with what it blocks."""
    found: list[dict[str, Any]] = []

    if not uses_dedicated_profile(config) and chrome_running():
        found.append(
            {
                "code": "chrome_running",
                "blocks": ["discovery", "apply"],
                "message": (
                    "Google Chrome is open, and this bot drives your real Chrome profile "
                    f"({resolve_chrome_profile_dir(config)})."
                ),
                "fix": (
                    "Quit Chrome completely — including the background/tray process — then "
                    "start again. Close this dashboard's own Chrome tabs too; Chrome locks "
                    "its profile while any window is open."
                ),
            }
        )

    facts_path = config.base_dir / "profile" / "resume_facts.yaml"
    if not facts_path.exists():
        found.append(
            {
                "code": "resume_facts_missing",
                "blocks": ["discovery", "apply"],
                "message": f"Resume facts are missing: {facts_path}",
                "fix": "Copy profile.example/resume_facts.yaml to profile/resume_facts.yaml and fill it in.",
            }
        )

    if not config.user.email:
        found.append(
            {
                "code": "email_missing",
                "blocks": ["apply"],
                "message": "user.email is empty in config.yaml.",
                "fix": "Set user.email — application forms require it.",
            }
        )

    if not config.resume_path.exists():
        found.append(
            {
                "code": "resume_missing",
                "blocks": ["apply"],
                "message": f"Resume PDF not found: {config.resume_path}",
                "fix": f"Put your resume at {config.resume.path} (or update resume.path in config.yaml).",
            }
        )

    return found


def blocking_for(config: Any, kind: str) -> list[dict[str, Any]]:
    return [item for item in blockers(config) if kind in item.get("blocks", [])]


def describe(items: list[dict[str, Any]]) -> str:
    """Single-line, human-readable summary suitable for an HTTP 409 detail."""
    return " ".join(f"{item['message']} {item['fix']}" for item in items).strip()
