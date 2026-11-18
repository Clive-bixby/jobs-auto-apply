"""Run manager for the web dashboard.

Discovery and apply both call straight into the existing CLI coroutines
(``cli._review`` and ``cli._apply_reviewed_cmd``). Nothing about how jobs are
discovered, scored, reviewed or submitted is reimplemented here — this module
only:

* serialises runs (one browser automation session at a time),
* applies the dashboard preference overlay to the in-memory config,
* records progress by diffing the bot's own data files before/after a run,
* captures the portion of ``data/run.log`` the run appended.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .preferences import PLATFORMS, apply_to_config, load_preferences

logger = logging.getLogger("job_apply")

MAX_RUNS = 40
LOG_TAIL_CHARS = 24_000
KINDS = ("discovery", "apply")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    id: str
    kind: str
    platform: str
    started_at: str
    status: str = "running"  # running | succeeded | failed | stopped
    finished_at: str | None = None
    error: str | None = None
    discovered: int = 0
    applied: int = 0
    log: str = ""

    def public(self, *, include_log: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_log:
            data.pop("log", None)
        return data


class RunBusy(RuntimeError):
    """Another run is already in flight."""


class AutomationPaused(RuntimeError):
    """Automation is paused from the dashboard."""


class AutomationController:
    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent.resolve()
        self.runs: list[RunRecord] = []
        self.current: RunRecord | None = None
        self._task: asyncio.Task | None = None
        self._log_offset = 0
        self._file_lock = threading.Lock()
        self._load_runs()

    # ---------------------------------------------------------------- storage

    @property
    def runs_path(self) -> Path:
        return self.base_dir / "data" / "web" / "runs.json"

    def _load_runs(self) -> None:
        path = self.runs_path
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict):
                continue
            try:
                record = RunRecord(
                    id=str(entry.get("id") or uuid.uuid4().hex[:8]),
                    kind=str(entry.get("kind") or "discovery"),
                    platform=str(entry.get("platform") or "all"),
                    started_at=str(entry.get("started_at") or _now_iso()),
                    status=str(entry.get("status") or "succeeded"),
                    finished_at=entry.get("finished_at"),
                    error=entry.get("error"),
                    discovered=int(entry.get("discovered") or 0),
                    applied=int(entry.get("applied") or 0),
                    log=str(entry.get("log") or ""),
                )
            except (TypeError, ValueError):
                continue
            if record.status == "running":
                # The server died while this run was in flight.
                record.status = "stopped"
                record.error = record.error or "interrupted by a server restart"
            self.runs.append(record)
        self.runs = self.runs[:MAX_RUNS]

    def _persist(self) -> None:
        with self._file_lock:
            path = self.runs_path
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = []
            for record in self.runs[:MAX_RUNS]:
                entry = record.public(include_log=True)
                entry["log"] = record.log[-LOG_TAIL_CHARS:]
                payload.append(entry)
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # ----------------------------------------------------------------- helpers

    def _applied_jobs_path(self) -> Path:
        from ..config import load_config

        try:
            return load_config(self.config_path).applied_jobs_path
        except Exception:
            return self.base_dir / "data" / "applied_jobs.json"

    def _applied_count(self) -> int:
        from ..applied_report import load_history

        # Count submitted applications, not ledger rows: the ledger also records
        # abandoned and deferred jobs.
        return sum(
            1
            for row in load_history(self._applied_jobs_path())
            if str(row.get("status", "")).strip() == "applied"
        )

    def _queue_total(self) -> int:
        from ..review import items_from_payload, load_review_queue

        review_dir = "data/review"
        try:
            from ..config import load_config

            review_dir = load_config(self.config_path).application.review_dir
        except Exception:
            pass
        total = 0
        for name in PLATFORMS:
            queue = load_review_queue(self.base_dir, name, review_dir)
            total += len(items_from_payload(queue))
        return total

    def _log_size(self) -> int:
        try:
            return self._log_path().stat().st_size
        except OSError:
            return 0

    def _log_path(self) -> Path:
        try:
            from ..config import load_config

            return load_config(self.config_path).log_path
        except Exception:
            return self.base_dir / "data" / "run.log"

    def _read_log_from_offset(self) -> str:
        path = self._log_path()
        try:
            size = path.stat().st_size
        except OSError:
            return ""
        start = self._log_offset if 0 <= self._log_offset <= size else 0
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return text[-LOG_TAIL_CHARS:]

    # ------------------------------------------------------------------ state

    def find(self, run_id: str) -> RunRecord | None:
        if self.current and self.current.id == run_id:
            return self.current
        return next((record for record in self.runs if record.id == run_id), None)

    def snapshot(self) -> dict[str, Any]:
        prefs = load_preferences(self.base_dir)
        return {
            "busy": self.current is not None,
            "paused": bool(prefs["paused"]),
            "current": self.current.public() if self.current else None,
            "runs": [record.public() for record in self.runs[:12]],
        }

    # ------------------------------------------------------------------ start

    def start(self, kind: str, platform: str, *, limit: int | None = None) -> RunRecord:
        if kind not in KINDS:
            raise ValueError(f"unknown run kind: {kind}")
        if self.current is not None:
            raise RunBusy("a run is already in progress")

        prefs = load_preferences(self.base_dir)
        if prefs["paused"]:
            raise AutomationPaused("automation is paused — resume it before starting a run")

        record = RunRecord(
            id=uuid.uuid4().hex[:8],
            kind=kind,
            platform=platform,
            started_at=_now_iso(),
        )
        self.current = record
        self.runs.insert(0, record)
        del self.runs[MAX_RUNS:]
        self._log_offset = self._log_size()
        self._task = asyncio.create_task(self._execute(record, limit))
        self._persist()
        return record

    async def stop(self) -> bool:
        task = self._task
        if task is None or task.done():
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        return True

    async def _execute(self, record: RunRecord, limit: int | None) -> None:
        from ..cli import _apply_reviewed_cmd, _review
        from ..config import load_config

        before_applied = 0
        before_queue = 0
        try:
            before_applied = self._applied_count()
            before_queue = self._queue_total()
        except Exception:
            logger.debug("Could not read pre-run counters", exc_info=True)

        prefs = load_preferences(self.base_dir)

        def mutator(config: Any) -> None:
            apply_to_config(config, prefs)
            if limit and int(limit) > 0:
                config.application.jobs_per_platform = int(limit)

        cancelled = False
        try:
            logger.info(
                "Dashboard: starting %s run for %s (dry_run overlay=%s)",
                record.kind,
                record.platform,
                prefs.get("apply_mode", "inherit"),
            )
            if record.kind == "discovery":
                await _review(
                    self.config_path,
                    record.platform,
                    True,
                    False,
                    False,
                    config_mutator=mutator,
                )
            else:
                await _apply_reviewed_cmd(
                    self.config_path,
                    record.platform,
                    False,
                    config_mutator=mutator,
                )
            record.status = "succeeded"
        except asyncio.CancelledError:
            cancelled = True
            record.status = "stopped"
            record.error = "stopped from the dashboard"
            raise
        except SystemExit as exc:
            record.status = "failed"
            record.error = f"aborted (prerequisite): {exc}"
        except Exception as exc:  # noqa: BLE001 - surfaced to the dashboard
            from ..chrome_profile import ChromeProfileLockedError

            record.status = "failed"
            if isinstance(exc, ChromeProfileLockedError):
                # The single most common cause: the bot drives the real Chrome
                # profile, which Chrome locks while it is open.
                record.error = (
                    "Chrome is open. Quit Chrome completely (including its background "
                    "process), then start the run again — the bot needs exclusive use "
                    "of your Chrome profile."
                )
            else:
                record.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Dashboard: %s run failed", record.kind)
        finally:
            record.log = self._read_log_from_offset()
            record.finished_at = record.finished_at or _now_iso()
            if record.status == "running":
                record.status = "succeeded"
            try:
                record.applied = max(0, self._applied_count() - before_applied)
            except Exception:
                pass
            try:
                record.discovered = max(0, self._queue_total() - before_queue)
            except Exception:
                pass
            self.current = None
            self._task = None
            self._persist()
            logger.info(
                "Dashboard: %s run %s finished with status %s (+%d discovered, +%d applied)",
                record.kind,
                record.id,
                record.status,
                record.discovered,
                record.applied,
            )
            if cancelled:
                raise asyncio.CancelledError()
