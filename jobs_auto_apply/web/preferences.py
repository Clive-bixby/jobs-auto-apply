"""Dashboard preferences, stored beside the bot's other state files.

``config.yaml`` stays the single source of truth for the CLI. The dashboard
never rewrites it: preferences set in the UI are persisted to
``data/web/preferences.json`` and applied *in memory* to the config object for
runs the dashboard triggers. That keeps browser profiles, sessions, secrets and
hand-written config comments untouched.

Three-state values:
  * ``None``  -> inherit whatever ``config.yaml`` says
  * explicit  -> override for dashboard-triggered runs only
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

PLATFORMS = ("wellfound", "uplers", "naukri", "hirist", "instahyre")

APPLY_MODES = ("inherit", "dry", "live")

_DEFAULT: dict[str, Any] = {
    "paused": False,
    "apply_mode": "inherit",
    "discovery_limit": 10,
    "platforms": {name: {"enabled": None, "keywords": ""} for name in PLATFORMS},
}

_lock = threading.Lock()


def preferences_path(base_dir: Path) -> Path:
    return base_dir / "data" / "web" / "preferences.json"


def defaults() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULT)


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    prefs = defaults()
    if not isinstance(raw, dict):
        return prefs

    prefs["paused"] = bool(raw.get("paused", False))

    mode = str(raw.get("apply_mode", "inherit")).strip().lower()
    prefs["apply_mode"] = mode if mode in APPLY_MODES else "inherit"

    try:
        limit = int(raw.get("discovery_limit", prefs["discovery_limit"]))
    except (TypeError, ValueError):
        limit = prefs["discovery_limit"]
    prefs["discovery_limit"] = max(1, min(limit, 200))

    platforms = raw.get("platforms")
    if isinstance(platforms, dict):
        for name in PLATFORMS:
            entry = platforms.get(name)
            if not isinstance(entry, dict):
                continue
            enabled = entry.get("enabled")
            prefs["platforms"][name]["enabled"] = None if enabled is None else bool(enabled)
            prefs["platforms"][name]["keywords"] = str(entry.get("keywords") or "").strip()
    return prefs


def load_preferences(base_dir: Path) -> dict[str, Any]:
    path = preferences_path(base_dir)
    if not path.exists():
        return defaults()
    try:
        return _coerce(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return defaults()


def save_preferences(base_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the stored preferences and return the new state."""
    with _lock:
        current = load_preferences(base_dir)
        merged = copy.deepcopy(current)
        if "paused" in patch:
            merged["paused"] = bool(patch["paused"])
        if "apply_mode" in patch:
            merged["apply_mode"] = patch["apply_mode"]
        if "discovery_limit" in patch:
            merged["discovery_limit"] = patch["discovery_limit"]
        platforms = patch.get("platforms")
        if isinstance(platforms, dict):
            for name, entry in platforms.items():
                if name in PLATFORMS and isinstance(entry, dict):
                    merged["platforms"].setdefault(name, {"enabled": None, "keywords": ""})
                    merged["platforms"][name].update(entry)

        merged = _coerce(merged)
        path = preferences_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return merged


def apply_to_config(config: Any, prefs: dict[str, Any]) -> None:
    """Apply the dashboard overlay to an in-memory ``AppConfig``.

    Only runs triggered from the dashboard see these values; a normal
    ``python main.py run`` still reads ``config.yaml`` as-is.
    """
    application = config.application

    mode = prefs.get("apply_mode", "inherit")
    if mode == "dry":
        application.dry_run = True
    elif mode == "live":
        application.dry_run = False

    try:
        limit = int(prefs.get("discovery_limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit > 0:
        # Doubles as the discovery target and the per-platform apply batch cap,
        # matching how `review` / `apply-reviewed` already read this value.
        application.jobs_per_platform = limit

    platform_prefs = prefs.get("platforms") or {}
    for name in PLATFORMS:
        entry = platform_prefs.get(name)
        if not isinstance(entry, dict):
            continue
        platform = getattr(config, name, None)
        if platform is None:
            continue
        if entry.get("enabled") is not None:
            platform.enabled = bool(entry["enabled"])

        keywords = str(entry.get("keywords") or "").strip()
        if not keywords or not platform.enabled:
            continue
        filters = getattr(platform, "filters", None)
        if filters is None:
            continue
        current = getattr(filters, "keywords", None)
        if isinstance(current, str):
            filters.keywords = keywords
        elif isinstance(current, list):
            filters.keywords = [part.strip() for part in keywords.split(",") if part.strip()]
        elif hasattr(filters, "roles"):
            filters.roles = [part.strip() for part in keywords.split(",") if part.strip()]


def resolved_platforms(config: Any, prefs: dict[str, Any]) -> dict[str, bool]:
    """Effective enabled/disabled state per platform, after the overlay."""
    overrides = prefs.get("platforms") or {}
    out: dict[str, bool] = {}
    for name in PLATFORMS:
        base = bool(getattr(getattr(config, name, None), "enabled", False))
        entry = overrides.get(name) or {}
        enabled = entry.get("enabled")
        out[name] = base if enabled is None else bool(enabled)
    return out
