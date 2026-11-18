"""Answer every pending screening question from profile data (non-interactive).

Uses the exact save path the interactive `answer-questions` flow uses, so
validation/coercion behaves identically. Usage:
    python scripts/_answer_pending.py          # save answers
    python scripts/_answer_pending.py --dry    # only show what would happen
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobs_auto_apply.config import load_config  # noqa: E402
from jobs_auto_apply.pending_questions import (  # noqa: E402
    _remove_group,
    _save_pending_group_answers,
    pending_groups,
    pending_question_list,
    prune_answered,
)

# Answers derived from profile/application_facts.yaml, profile/resume_facts.yaml
# and data/user_memory.json. Keyed on the live question wording (normalised).
ANSWERS: dict[str, str] = {
    "in which domain have you managed projects or programs": "Technology",
    "is there any gap in your experiences": "No",
    "do you have 4+ years of node dev exp": "No",
    "how many years of experience do you have in bedrock": "0",
    "do you have experience with langchain langgraph mlflow": "no",
    "how many years of experience do you have in aiml": "1",
    "how many years of experience do you have in aem": "0",
    "have you developed and implemented user interfaces for our web platforms focused on supply chain finance": "No",
    "having experience in design and develop responsive web interfaces using reactjs nodejs and other relevant frontend technologies": "1",
    "have you ever worked collaboratively with the ux/ui design team to translate designs and wireframes into highquality code": "No",
    "your experience in front end development proficiency in reactjs html5 css3 ui style guiding knowledge and javascript": "1",
    "are you a frontend developer with a minimum of 3 years of experience": "No",
    "what are your expectations": "8 LPA",
    "is your current company is product based or service based": "Product Based",
    "total year of experience": "1",
    "total experience as a frontend developer": "1",
    "how many years of experience do you have developing with ruby on rails": "0",
    "have you built responsive web applications that support desktop tablet and mobile devices": "Yes, on a few projects",
    "have you integrated frontend applications with backend services": "Yes, extensively",
    "reactjs + react native experience": "React.js: 1 year; React Native: 0",
    "nextjs & typescript experience": "Next.js: 1 year; TypeScript: 1 year",
    "total experience 46 years": "1",
    "do you have 36 years of professional experience developing applications using react and typescript": "No",
    "do you have experience building scalable componentbased applications and working with state management libraries redux context api zustand etc": "Yes",
    "do you have leadership experiecne": "No",
    "how many years of experience do you have in jscript": "1",
    "how many years of experience do you have with apache kafka or rabbitmq": "0",
    "how many years of experience in system design or design patterns": "1",
    "how many years of experience do you have in sap s4 hana abap oo": "0",
    "which of these locations are you willing to relocate to": "Mumbai, Pune, Hyderabad",
    "what role / roles you are applying for": "Full Stack Developer",
    "how many years of experience do you have in microsoft visual studio code": "1",
    "how many years of experience do you have in numpy and pandas": "0",
    "are you interested to work on contract to hire c2h basis under cerebra it payroll": "Yes",
    "do you have pf for all of your employments": "No",
    "how many years of experience do you have in video analytics": "No experience",
    "what is your current location": "Gurgaon",
    "have you worked in any observability tool grafana prometheus": "No",
    "how many years of experience do you have in amplify": "0",
    "in which framework do you have expertise": "Fast API",
    "what is your college/university name": "Indian Institute of Technology Roorkee",
    "how many years of experience do you have in b2c and fintech": "0",
    # Common variants that may be grouped with the above
    "total year of experience?": "1",
    "how many years of experience do you have in total": "1",
    # --- Batch 2 (queued by the 23:20 run) ---
    "how many years of python experience do you have": "1",
    "how many years of django experience do you have": "1",
    "how many years of azure experience do you have": "0",
    "what is your exp in nodejs": "1 year",
    "are you more towards backend or frontend": "Backend",
    "how many years of experience do you have in multithreading and concurrency": "0",
    "this is for permanent position with for infosys are you ok": "Yes",
    "how many years of experience do you have in team management": "No experience",
    "do you have experience working on etl extract transform load processes if yes please mention the number of years": "0",
    "current ctc and expected ctc": "0/8",
    "how many years of experience do you have in lamda": "1",
    "how many years of experience do you have in pandas and numpy": "0",
    "is your qualification full time": "Yes",
    "how many years of experience do you have in pandas": "0",
    "have you shared details or attended interview with altimetrik or any of its vendor in last 45 days": "No",
}

# Some questions repeat verbatim with *different* option sets, so the answer has to
# be chosen per group (keyed by pending-question group id), not per wording.
SPECIFIC: dict[str, str] = {
    "unique:fef96a963565009d": "Full Stack Developer React.js + Node.js + AWS",
    "unique:f65fcd036481844b": "Gurugram",
    # unique:d4502d68fc1058d5 "expereince in any of the below domains?" offers only
    # Market Risk / Counterparty credit risk / Capital Markets — none of which the
    # profile has, so it is left for a human instead of guessed.
}


def adapt_to_options(answer: str, options: list[str], multi: bool) -> str | None:
    """Pick the offered option(s) that mean what ``answer`` says.

    A question can repeat verbatim with a different option set (e.g. "Which of
    these locations are you willing to relocate to?" listing only Bengaluru), so
    the stored wording-level answer must be narrowed to what is on screen.
    """
    if not options:
        return answer
    picked: list[str] = []
    for part in [p.strip() for p in answer.split(",") if p.strip()]:
        match = next((o for o in options if norm(o) == norm(part)), None)
        if match is None:
            match = next(
                (
                    o
                    for o in options
                    if norm(part) and (norm(part) in norm(o) or norm(o) in norm(part))
                ),
                None,
            )
        if match and match not in picked:
            picked.append(match)
    if not picked:
        return None
    return ", ".join(picked) if multi else picked[0]


def answer_for_group(group, options: list[str], multi: bool, preferred: list[str]) -> str | None:
    if group.group_id == "preferred_location" and options:
        # Ordered by the profile's preference list, not the site's option order.
        ordered = [loc for loc in preferred if any(norm(loc) in norm(o) for o in options)]
        return ", ".join(ordered[:3]) if ordered else None
    answer = SPECIFIC.get(group.group_id) or lookup(list(group.variants))
    if answer is None:
        return None
    return adapt_to_options(answer, options, multi)


def norm(text: str) -> str:
    # Separator-insensitive: "React.js" == "react js", "4–6" == "46",
    # "high-quality" == "highquality".
    return "".join(ch for ch in text.lower() if ch.isalnum())


ANSWERS_NORM: dict[str, str] = {norm(k): v for k, v in ANSWERS.items()}


def lookup(variants: list[str]) -> str | None:
    for v in variants:
        key = norm(v)
        if key in ANSWERS_NORM:
            return ANSWERS_NORM[key]
    # tolerant substring match
    key = norm(variants[0]) if variants else ""
    for cand, ans in ANSWERS_NORM.items():
        if cand and (cand in key or key in cand):
            return ans
    return None


def main() -> int:
    dry = "--dry" in sys.argv
    config = load_config(Path("config.yaml"))
    base = config.base_dir
    groups = pending_groups(base, config)
    print(f"pending groups: {len(groups)}")

    # Options live on the raw entries, not on the grouped view.
    options_by_key: dict[str, list[str]] = {}
    for entry in pending_question_list(base, config):
        field = entry.get("field") or {}
        opts = [str(o).strip() for o in (field.get("options") or []) if str(o).strip()]
        if opts:
            options_by_key[str(entry.get("key", ""))] = opts
    from jobs_auto_apply.question_groups import classify_question  # noqa: E402

    options_by_group: dict[str, list[str]] = {}
    for entry in pending_question_list(base, config):
        field = entry.get("field") or {}
        opts = [str(o).strip() for o in (field.get("options") or []) if str(o).strip()]
        if opts:
            options_by_group.setdefault(classify_question(str(entry.get("question", ""))), opts)

    preferred = list(getattr(config.profile, "locations", []) or [])
    saved, failed, unmatched = [], [], []
    for group in groups:
        variants = list(group.variants)
        options = options_by_group.get(group.group_id, [])
        multi = any("," in o or " " in o for o in options) and len(options) > 2
        answer = answer_for_group(group, options, multi, preferred)
        if answer is None:
            unmatched.append(variants[0] if variants else group.group_id)
            continue
        if dry:
            print(f"  [dry] {variants[0][:70]!r} -> {answer!r}")
            continue
        job = group.jobs[0] if group.jobs else {}
        stored = _save_pending_group_answers(
            base,
            group,
            answer,
            config,
            company=str(job.get("company", "")),
            job_title=str(job.get("title", "")),
        )
        if stored:
            _remove_group(base, group.group_id)
            saved.append((variants[0], stored[0]))
        else:
            failed.append((variants[0], answer))

    if not dry:
        removed = prune_answered(base, config)
        print(f"\nsaved={len(saved)} failed_validation={len(failed)} unmatched={len(unmatched)} pruned_extra={removed}")
        for q, a in saved:
            print(f"  OK  {q[:70]} -> {a}")
        for q, a in failed:
            print(f"  FAIL {q[:70]} -> {a!r} (rejected by validation)")
        for q in unmatched:
            print(f"  NO-MAP {q[:70]}")
        from jobs_auto_apply.pending_questions import pending_count

        print(f"remaining pending questions: {pending_count(base, config)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
