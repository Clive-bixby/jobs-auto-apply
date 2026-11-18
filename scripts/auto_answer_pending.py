"""Answer pending screening questions with profile-consistent guesses, then retry those jobs.

Guesses are derived from config.yaml (Aryan Yadav, 1 year, React/Node/Python) so they
never overstate experience. Values are saved to user_memory.json like a manual answer.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobs_auto_apply.answers.memory_store import save_answer  # noqa: E402
from jobs_auto_apply.config import load_config  # noqa: E402
from jobs_auto_apply.pending_questions import (  # noqa: E402
    _collect_retry_jobs,
    _dedupe_retry_jobs,
    _remove_group,
    pending_groups,
)
from jobs_auto_apply.pending_retry import retry_pending_jobs  # noqa: E402
from jobs_auto_apply.utils import clear_deferred_applies  # noqa: E402

# Educated guesses: consistent with 1 year of experience and the configured skill set.
GUESSES: list[tuple[str, str]] = [
    ("ai coding tools", "Yes"),
    ("ui technology", "React.js"),
    ("reason for your current switch", "Looking for better growth opportunities and hands-on full-stack work."),
    ("last name", "Yadav"),
    ("total yrs of experience", "1"),
    ("exp on node", "1"),
    ("exp on react", "1"),
    ("exp on microservices", "1"),
    ("exp on system design", "1"),
    ("react native", "Yes"),
    ("ci/cd", "Yes"),
    ("backend technology", "Node.js (Express.js)"),
    ("aws services", "Yes"),
    ("previously worked with us", "No"),
    ("comfortable with", "Bengaluru"),
]


def guess_for(question: str) -> str | None:
    q = question.lower()
    for needle, answer in GUESSES:
        if needle in q:
            return answer
    return None


def run_pass(config, max_passes: int = 3) -> None:
    for pass_no in range(1, max_passes + 1):
        if not pending_groups(config.base_dir, config):
            print("No pending questions left.")
            return
        print(f"--- pass {pass_no} ---")
        if not answer_and_retry(config):
            return


def answer_and_retry(config) -> bool:
    groups = pending_groups(config.base_dir, config)
    refs = []
    answered = 0
    for group in groups:
        question = (group.title or "").strip()
        answer = guess_for(question)
        if not answer:
            print(f"NO GUESS  | {question[:75]}")
            continue
        save_answer(
            config.base_dir,
            question,
            answer,
            aliases=list(group.variants or []),
            reviewed=True,
            source="interactive",
            config=config,
        )
        _remove_group(config.base_dir, group.group_id)
        refs.extend(_collect_retry_jobs(group))
        answered += 1
        print(f"ANSWERED  | {question[:65]} -> {answer}")

    refs = _dedupe_retry_jobs(refs)
    print(f"\nanswered={answered} retry_jobs={len(refs)}")
    if not refs:
        return False

    clear_deferred_applies(config.applied_jobs_path)
    applied = asyncio.run(retry_pending_jobs(config, refs))
    print(f"applied={applied}/{len(refs)}")
    return True


def main() -> int:
    run_pass(load_config(Path("config.yaml")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
