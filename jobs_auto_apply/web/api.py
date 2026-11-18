"""REST surface for the dashboard.

Read endpoints are projections over the bot's existing files. Write endpoints
fall into exactly two buckets:

* review decisions  -> ``data/review/<platform>.json`` (the same queue
  ``main.py review`` writes and ``main.py apply-reviewed`` reads)
* run control      -> ``AutomationController`` which delegates to ``cli._review``
  and ``cli._apply_reviewed_cmd``

There is deliberately no endpoint that submits an application outside the
approved queue, and no endpoint that answers recruiter screening questions on
the user's behalf.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..applied_report import build_rows, export_applied_jobs, load_history
from ..config import load_config
from ..job_selection import score_job
from ..profile_data import load_resume_facts
from ..review import (
    build_review_payload,
    items_from_payload,
    load_review_queue,
    review_summary,
    save_review_queue,
)
from ..technical_failures import load_technical_failures
from .controller import AutomationController, AutomationPaused, RunBusy
from .manual_applications import (
    PLATFORM_CHOICES,
    add_manual_application,
    delete_manual_application,
)
from .preferences import (
    APPLY_MODES,
    PLATFORMS,
    load_preferences,
    resolved_platforms,
    save_preferences,
)
from .preflight import blockers as preflight_blockers
from .preflight import blocking_for, describe

router = APIRouter(prefix="/api")

_queue_lock = threading.Lock()


# --------------------------------------------------------------------- helpers


def _config(request: Request) -> Any:
    try:
        return load_config(Path(request.app.state.config_path))
    except Exception as exc:  # noqa: BLE001 - surface a readable error
        raise HTTPException(status_code=500, detail=f"could not load config: {exc}") from exc


def _controller(request: Request) -> AutomationController:
    return request.app.state.controller


def _queue(request: Request, platform: str) -> Any:
    config = _config(request)
    return items_from_payload(
        load_review_queue(config.base_dir, platform, config.application.review_dir)
    )


def _tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _serialize_item(config: Any, item: Any, facts: Any) -> dict[str, Any]:
    try:
        fit = score_job(config, item, facts=facts)
        score = {
            "score": round(fit.total, 2),
            "salary_score": round(fit.salary, 2),
            "profile_score": round(fit.profile, 2),
            "eligible": fit.eligible,
            "score_reason": fit.reason,
        }
    except Exception:  # noqa: BLE001 - a bad item must not break the list
        score = {
            "score": 0.0,
            "salary_score": 0.0,
            "profile_score": 0.0,
            "eligible": None,
            "score_reason": "score unavailable",
        }

    meta = item.meta or {}
    return {
        "job_key": item.job_key,
        "platform": item.source,
        "job_id": item.job_id,
        "title": item.title,
        "company": item.company,
        "url": item.url,
        "status": item.status,
        "easy_apply": item.easy_apply,
        "external_ats": item.external_ats,
        "external_url": item.external_url,
        "jd": item.jd_excerpt,
        "cover_letter": item.cover_letter,
        "salary_display": meta.get("salary_display") or "",
        "salary_eligible": meta.get("salary_eligible"),
        "salary_reason": meta.get("salary_reason") or "",
        "location_blocked": bool(meta.get("location_blocked")),
        "resume": config.resume.path,
        **score,
    }


# -------------------------------------------------------------------- payloads


class DecisionPayload(BaseModel):
    job_keys: list[str] = Field(min_length=1)
    status: Literal["pending", "approved", "rejected"]


class StartRunPayload(BaseModel):
    platform: str = "all"
    limit: int | None = Field(default=None, ge=1, le=200)


class PausePayload(BaseModel):
    paused: bool


class PlatformPref(BaseModel):
    enabled: bool | None = None
    keywords: str = ""


class PreferencesPayload(BaseModel):
    paused: bool | None = None
    apply_mode: Literal["inherit", "dry", "live"] | None = None
    discovery_limit: int | None = Field(default=None, ge=1, le=200)
    platforms: dict[str, PlatformPref] = Field(default_factory=dict)


class ManualApplicationPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=2000)
    platform: str = Field(default="manual", max_length=40)
    applied_at: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=2000)


# ------------------------------------------------------------------ read: state


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    config = _config(request)
    prefs = load_preferences(config.base_dir)
    controller = _controller(request)

    queue_counts = {name: review_summary(config.base_dir, name, config.application.review_dir) for name in PLATFORMS}
    totals = {
        "pending": sum(c.get("pending", 0) for c in queue_counts.values()),
        "approved": sum(c.get("approved", 0) for c in queue_counts.values()),
        "rejected": sum(c.get("rejected", 0) for c in queue_counts.values()),
    }

    try:
        # Only rows the bot actually marked "applied": the ledger also keeps
        # abandoned/deferred rows, which are not submissions.
        applied_total = sum(
            1
            for row in load_history(config.applied_jobs_path)
            if str(row.get("status", "")).strip() == "applied"
        )
    except Exception:
        applied_total = 0

    try:
        failures = len(load_technical_failures(config.base_dir))
    except Exception:
        failures = 0

    try:
        from ..pending_questions import pending_count

        questions = pending_count(config.base_dir, config)
    except Exception:
        questions = 0

    enabled = resolved_platforms(config, prefs)
    snapshot = controller.snapshot()

    # While a run is in flight the automation has its *own* Chrome window open on
    # this profile, so the "Chrome is open" check would be a false positive.
    found_blockers = preflight_blockers(config)
    if snapshot["busy"]:
        found_blockers = [b for b in found_blockers if b["code"] != "chrome_running"]

    return {
        "automation": {
            **snapshot,
            "apply_mode": prefs["apply_mode"],
            "discovery_limit": prefs["discovery_limit"],
            "effective_dry_run": True
            if prefs["apply_mode"] == "dry"
            else (False if prefs["apply_mode"] == "live" else bool(config.application.dry_run)),
            "require_review": bool(config.application.require_review),
        },
        "counts": {
            "discovered": totals["pending"] + totals["approved"] + totals["rejected"],
            "pending": totals["pending"],
            "approved": totals["approved"],
            "rejected": totals["rejected"],
            "applied": applied_total,
            "failures": failures,
            "questions": questions,
        },
        "by_platform": {
            name: {**queue_counts[name], "enabled": enabled[name], "label": name.title()}
            for name in PLATFORMS
        },
        # Prerequisites a browser run needs, e.g. Chrome must be closed when the
        # bot drives the real Chrome profile. Reported up front, not after the run.
        "blockers": found_blockers,
        "config": {
            "resume": config.resume.path,
            "resume_exists": config.resume_path.exists(),
            "email": bool(config.user.email),
            "review_dir": config.application.review_dir,
            "min_inr_salary_lpa": config.application.min_inr_salary_lpa,
            "one_job_per_company": bool(config.application.one_job_per_company),
            "skip_ineligible_salary": bool(config.application.skip_ineligible_salary),
            "parallel_platforms": bool(config.application.parallel_platforms),
        },
    }


@router.get("/platforms")
def platforms(request: Request) -> dict[str, Any]:
    config = _config(request)
    prefs = load_preferences(config.base_dir)
    enabled = resolved_platforms(config, prefs)

    out: dict[str, Any] = {}
    for name in PLATFORMS:
        platform = getattr(config, name, None)
        filters = getattr(platform, "filters", None)
        keywords = getattr(filters, "keywords", None)
        roles = getattr(filters, "roles", None)
        search_urls = getattr(filters, "search_urls", None)
        feeds = getattr(filters, "feeds", None)

        if isinstance(keywords, list):
            summary = ", ".join(str(k) for k in keywords)
            editable = True
        elif isinstance(keywords, str):
            summary = keywords
            editable = True
        elif isinstance(roles, list):
            summary = ", ".join(str(r) for r in roles)
            editable = True
        else:
            summary = ""
            editable = False

        out[name] = {
            "name": name,
            "label": name.title(),
            "enabled": enabled[name],
            "config_enabled": bool(getattr(platform, "enabled", False)),
            "keywords": summary,
            "keywords_editable": editable,
            "search_urls": list(search_urls or []),
            "feed_count": len(feeds or []),
        }
    return {"platforms": out}


@router.get("/jobs")
def jobs(
    request: Request,
    status_filter: Literal["all", "pending", "approved", "rejected"] = "all",
    platform: str = "all",
    q: str = "",
) -> dict[str, Any]:
    config = _config(request)
    try:
        facts = load_resume_facts(config.base_dir)
    except Exception:
        facts = None

    names = [platform] if platform in PLATFORMS else list(PLATFORMS)
    needle = q.strip().lower()
    items: list[dict[str, Any]] = []
    for name in names:
        for item in _queue(request, name):
            if status_filter != "all" and item.status != status_filter:
                continue
            blob = f"{item.title} {item.company} {item.jd_excerpt[:800]}".lower()
            if needle and needle not in blob:
                continue
            items.append(_serialize_item(config, item, facts))

    items.sort(key=lambda row: (-float(row.get("score") or 0), row.get("company") or ""))
    return {"items": items, "total": len(items)}


@router.get("/jobs/detail")
def job_detail(request: Request, key: str) -> dict[str, Any]:
    config = _config(request)
    try:
        facts = load_resume_facts(config.base_dir)
    except Exception:
        facts = None
    platform = key.split(":", 1)[0]
    if platform not in PLATFORMS:
        raise HTTPException(status_code=404, detail="unknown job key")
    for item in _queue(request, platform):
        if item.job_key == key:
            return _serialize_item(config, item, facts)
    raise HTTPException(status_code=404, detail="job not found in the review queue")


@router.get("/applications")
def applications(request: Request, platform: str = "all", q: str = "") -> dict[str, Any]:
    config = _config(request)
    history = load_history(config.applied_jobs_path)
    manual_keys = {
        str(entry.get("job_key"))
        for entry in history
        if isinstance(entry, dict) and entry.get("manual")
    }
    rows = build_rows(history)
    needle = q.strip().lower()

    out: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        row.pop("when", None)
        row["manual"] = str(row.get("job_key") or "") in manual_keys
        if platform != "all" and row.get("platform_key") != platform:
            continue
        if needle:
            blob = f"{row.get('role')} {row.get('company')} {row.get('status')}".lower()
            if needle not in blob:
                continue
        out.append(row)

    applied = sum(1 for row in out if row.get("status") == "applied")
    return {"items": out, "total": len(out), "applied": applied}


@router.get("/failures")
def failures(request: Request) -> dict[str, Any]:
    config = _config(request)
    try:
        items = load_technical_failures(config.base_dir)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"could not read failures: {exc}") from exc
    return {"items": items, "total": len(items)}


@router.get("/logs")
def logs(request: Request, lines: int = 250) -> dict[str, Any]:
    config = _config(request)
    lines = max(20, min(int(lines), 2000))
    logs_dir = config.base_dir / "data" / "logs"
    available: list[str] = []
    if logs_dir.exists():
        available = sorted(
            (p.name for p in logs_dir.glob("*.log")),
            key=lambda name: (logs_dir / name).stat().st_mtime,
            reverse=True,
        )[:20]
    return {
        "path": str(config.log_path),
        "content": _tail(config.log_path, lines),
        "files": available,
    }


@router.get("/questions")
def questions(request: Request) -> dict[str, Any]:
    """Read-only view of deferred screening questions.

    Answering these is a recruiter-facing action, so the dashboard shows them
    but never answers them. Use ``python main.py answer-questions``.
    """
    config = _config(request)
    try:
        from ..pending_questions import pending_question_list

        items = pending_question_list(config.base_dir, config)
    except Exception:
        items = []
    return {"items": items, "total": len(items)}


@router.get("/runs")
def runs(request: Request) -> dict[str, Any]:
    return _controller(request).snapshot()


@router.get("/runs/{run_id}")
def run_detail(request: Request, run_id: str) -> dict[str, Any]:
    record = _controller(request).find(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.public(include_log=True)


# --------------------------------------------------------------- write: review


@router.post("/jobs/decision")
def decide(request: Request, payload: DecisionPayload) -> dict[str, Any]:
    """Approve / reject / un-decide queue items.

    This is the only path to approval; the apply run only ever reads items with
    ``status == "approved"`` via the bot's existing ``apply-reviewed`` flow.
    """
    config = _config(request)
    review_dir = config.application.review_dir

    by_platform: dict[str, set[str]] = {}
    for key in payload.job_keys:
        platform = key.split(":", 1)[0]
        if platform not in PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform in key: {key}")
        by_platform.setdefault(platform, set()).add(key)

    changed = 0
    missing: list[str] = []

    with _queue_lock:
        for platform, keys in by_platform.items():
            items = items_from_payload(load_review_queue(config.base_dir, platform, review_dir))
            touched = False
            for item in items:
                if item.job_key in keys:
                    if item.status != payload.status:
                        item.status = payload.status
                        changed += 1
                    touched = True
            if touched:
                save_review_queue(
                    config.base_dir,
                    platform,
                    build_review_payload(platform, items),
                    review_dir,
                )
            missing.extend(key for key in keys if key not in {item.job_key for item in items})

    return {
        "changed": changed,
        "status": payload.status,
        "missing": missing,
        "counts": {
            name: review_summary(config.base_dir, name, review_dir) for name in PLATFORMS
        },
    }


# ----------------------------------------------------------------- write: runs


@router.post("/control/discovery")
async def start_discovery(request: Request, payload: StartRunPayload) -> dict[str, Any]:
    controller = _controller(request)
    if payload.platform != "all" and payload.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail="unknown platform")
    if controller.current is not None:
        raise HTTPException(status_code=409, detail="a run is already in progress")
    blocked = blocking_for(_config(request), "discovery")
    if blocked:
        raise HTTPException(status_code=409, detail=describe(blocked))
    try:
        record = controller.start("discovery", payload.platform, limit=payload.limit)
    except RunBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AutomationPaused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"started": True, "run": record.public()}


@router.post("/control/apply")
async def start_apply(request: Request, payload: StartRunPayload) -> dict[str, Any]:
    controller = _controller(request)
    if payload.platform != "all" and payload.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail="unknown platform")
    if controller.current is not None:
        raise HTTPException(status_code=409, detail="a run is already in progress")
    blocked = blocking_for(_config(request), "apply")
    if blocked:
        raise HTTPException(status_code=409, detail=describe(blocked))
    try:
        record = controller.start("apply", payload.platform, limit=payload.limit)
    except RunBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AutomationPaused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"started": True, "run": record.public()}


@router.post("/control/stop")
async def stop_run(request: Request) -> dict[str, Any]:
    stopped = await _controller(request).stop()
    return {"stopped": stopped}


@router.post("/control/pause")
def pause(request: Request, payload: PausePayload) -> dict[str, Any]:
    config = _config(request)
    prefs = save_preferences(config.base_dir, {"paused": payload.paused})
    return {"paused": prefs["paused"]}


# ---------------------------------------------------------- preferences (UI)


@router.get("/preferences")
def get_preferences(request: Request) -> dict[str, Any]:
    config = _config(request)
    prefs = load_preferences(config.base_dir)
    return {
        "preferences": prefs,
        "resolved": resolved_platforms(config, prefs),
        "apply_modes": list(APPLY_MODES),
        "config_dry_run": bool(config.application.dry_run),
        "config_jobs_per_platform": config.application.jobs_per_platform,
        "note": (
            "Dashboard preferences are stored in data/web/preferences.json and applied to "
            "runs started from this dashboard. config.yaml is never rewritten, so the CLI "
            "keeps using its own values."
        ),
    }


@router.put("/preferences")
def put_preferences(request: Request, payload: PreferencesPayload) -> dict[str, Any]:
    config = _config(request)
    patch: dict[str, Any] = {}
    if payload.paused is not None:
        patch["paused"] = payload.paused
    if payload.apply_mode is not None:
        patch["apply_mode"] = payload.apply_mode
    if payload.discovery_limit is not None:
        patch["discovery_limit"] = payload.discovery_limit
    if payload.platforms:
        patch["platforms"] = {
            name: {"enabled": entry.enabled, "keywords": entry.keywords}
            for name, entry in payload.platforms.items()
        }
    prefs = save_preferences(config.base_dir, patch)
    return {"preferences": prefs, "resolved": resolved_platforms(config, prefs)}


# ------------------------------------------------- manual application entries


def _refresh_exports(config: Any) -> None:
    """Keep data/applied_jobs.csv + .html in step with edits made here."""
    try:
        export_applied_jobs(config)
    except Exception:  # noqa: BLE001 - export is best-effort
        pass


@router.get("/applications/manual/options")
def manual_options() -> dict[str, Any]:
    return {"platforms": list(PLATFORM_CHOICES)}


@router.post("/applications/manual")
def add_manual(request: Request, payload: ManualApplicationPayload) -> dict[str, Any]:
    """Log an application you submitted outside this bot.

    Written to the bot's own ledger with a ``manual:`` job key, so it shows up in
    the history and export without ever shadowing a job the bot discovers.
    """
    config = _config(request)
    try:
        entry = add_manual_application(
            config.applied_jobs_path,
            title=payload.title,
            company=payload.company,
            url=payload.url,
            platform=payload.platform,
            applied_at=payload.applied_at,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _refresh_exports(config)
    return {"entry": entry}


@router.delete("/applications/manual")
def remove_manual(request: Request, key: str) -> dict[str, Any]:
    """Remove a manually added entry (bot-recorded rows are never touched)."""
    config = _config(request)
    if not delete_manual_application(config.applied_jobs_path, key):
        raise HTTPException(status_code=404, detail="manual entry not found")
    _refresh_exports(config)
    return {"deleted": True, "key": key}
