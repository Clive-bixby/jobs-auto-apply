"""Ephemeral, best-effort guesses for screening questions nothing else answers.

Used only after saved answers, config/facts answers, RAG rules and vector matches
all come back empty. A guess fills the current application so it is not deferred,
but it is NEVER written to user_memory: a wrong guess must not leak into later
applications, where the real answer (or a better guess) can be given.

Identity / government / demographic questions are never guessed.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from ..config import AppConfig
from ..profile.application_facts import load_application_facts
from ..question_groups import classify_question
from .compensation import format_lpa
from .fields import enrich_field_for_llm

logger = logging.getLogger("job_apply")

# Never invent identifiers or personal demographics.
_NEVER_GUESS = re.compile(
    r"\b(?:pan|uan|aadhaa?r|passport|ssn|social security|date of birth|\bdob\b|birth date|"
    r"gender|marital|caste|religion|blood group)\b",
    re.I,
)

# Questions where "No" is both truthful for this profile and safe.
_NEGATIVE_YESNO = re.compile(
    r"sponsor|work\s+visa|require\s+visa|previously\s+(?:employed|worked|applied|interviewed)"
    r"|worked\s+(?:at|for)\s+us|applied\s+(?:before|previously)|interviewed\s+before"
    r"|criminal|convicted|disabilit|accommodation|non[-\s]?compete|restrictive\s+covenant"
    r"|require\s+any\s+support",
    re.I,
)

_CHOICE_KINDS = {"radio", "checkbox", "checkbox_group", "single_choice", "multi_choice", "select", "dropdown"}
_MULTI_KINDS = {"checkbox_group", "multi_choice"}


def _options(field: dict[str, Any]) -> list[str]:
    raw = field.get("options") or field.get("answer_options") or []
    return [str(o).strip() for o in raw if str(o).strip()]


def _is_yes_no(options: list[str]) -> bool:
    lowered = {o.strip().lower() for o in options}
    return bool(lowered) and lowered <= {"yes", "no", "y", "n"}


def _skill_key(name: str) -> str:
    """Loose skill identity: 'React.js', 'React' and 'ReactJS' collapse together."""
    key = re.sub(r"[^a-z0-9+#]", "", str(name or "").lower())
    if key.endswith("js") and len(key) > 4:
        key = key[:-2]
    return key


def _skill_years(config: AppConfig, text: str) -> int | None:
    """Explicit years for the first skill named in *text* (application_facts)."""
    try:
        facts = load_application_facts(config)
    except Exception:
        return None
    skill_years = facts.get("skill_years")
    if not isinstance(skill_years, dict):
        return None
    lowered = (text or "").lower()
    for name, years in skill_years.items():
        phrase = str(name).replace("_", " ")
        if not phrase or not re.search(rf"\b{re.escape(phrase)}\b", lowered):
            continue
        try:
            return int(float(str(years).strip()))
        except (TypeError, ValueError):
            continue
    return None


def _band_bounds(text: str) -> tuple[float, float] | None:
    """Parse a numeric band label like '0-2 years', '<6 years', '8+ years'."""
    t = (text or "").lower().replace("\u2013", "-")
    if "no experience" in t or "fresher" in t:
        return (0.0, 0.0)
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None
    if "-" in t and len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    if re.search(r"[<>]|less than|up to|below", t):
        return (0.0, nums[0])
    if re.search(r"\+|above|more than|over", t):
        return (nums[0], 99.0)
    return (nums[0], nums[0])


def _choose_yes_no(question: str, config: AppConfig) -> str:
    q = question or ""
    if _NEGATIVE_YESNO.search(q):
        return "No"
    # Skill experience: answer honestly from explicit skill_years.
    if re.search(r"\b(?:experience|worked with|hands?.on|proficien\w*|knowledge|expertise)\b", q, re.I):
        years = _skill_years(config, q)
        if years is not None:
            return "Yes" if years > 0 else "No"
    return "Yes"


def _pick_option(
    question: str,
    field: dict[str, Any],
    config: AppConfig,
    job: Any,
) -> str | None:
    opts = _options(field)
    if not opts:
        return None

    options_norm = {o.strip().lower() for o in opts}
    is_multi = str(field.get("kind", "")).lower() in _MULTI_KINDS

    # Multi-select "which of these do you know" → tick the core skills present.
    if is_multi:
        core = {_skill_key(s) for s in config.profile.core_skills if str(s).strip()}
        matches = [o for o in opts if _skill_key(o) in core]
        if matches:
            return ", ".join(matches[:3])

    if _is_yes_no(opts):
        want = _choose_yes_no(question, config)
        for o in opts:
            if o.strip().lower().startswith(want.lower()):
                return o
        return opts[0]

    try:
        facts = load_application_facts(config)
    except Exception:
        facts = {}

    if re.search(r"location|city|based|relocat", question, re.I):
        places = [str(facts.get("current_location", "")).strip()]
        places += [str(p).strip() for p in (facts.get("preferred_locations") or [])]
        for place in places:
            if not place:
                continue
            for o in opts:
                if place.lower() in o.lower():
                    return o

    targets: list[float] = []
    if re.search(r"ctc|lpa|salary|compensation", question, re.I):
        targets.append(float(config.compensation.expected_ctc_lpa or 0))
    if re.search(r"years?|experience", question, re.I):
        targets.append(float(config.profile.years_experience or 0))
    for target in targets:
        for o in opts:
            bounds = _band_bounds(o)
            if bounds and bounds[0] <= target <= bounds[1]:
                return o

    if "yes" in options_norm:
        return next(o for o in opts if o.strip().lower() == "yes")

    placeholder = re.compile(r"^(?:select|choose|please select|--.*|-.*)$", re.I)
    return next((o for o in opts if not placeholder.match(o.strip())), opts[0])


def _profile_snippet(config: AppConfig) -> str:
    headline = (config.profile.headline or "Software Engineer").strip()
    years = int(config.profile.years_experience or 0)
    years_label = "1 year" if years == 1 else f"{years} years"
    skills = ", ".join(str(s).strip() for s in config.profile.core_skills[:5] if str(s).strip())
    if not skills:
        return f"{headline} with {years_label} of hands-on engineering experience."
    return (
        f"{headline} with {years_label} of hands-on experience building and shipping "
        f"production applications with {skills}, owning features end to end."
    )


def _free_text_guess(question: str, config: AppConfig, job: Any) -> str | None:
    q = question or ""
    try:
        facts = load_application_facts(config)
    except Exception:
        facts = {}

    group = classify_question(q)
    if group == "reason_for_change":
        reason = str(facts.get("reason_for_change", "")).strip()
        if reason:
            return reason

    company = str(getattr(job, "company", "") or "").strip()
    title = str(getattr(job, "title", "") or "").strip()

    if re.search(r"why.{0,40}(?:join|work|us|company)|what interests you|why should we|why do you want", q, re.I):
        target = f"the {title} role" if title else "this role"
        at_company = f" at {company}" if company else ""
        years = int(config.profile.years_experience or 0)
        years_label = "1 year" if years == 1 else f"{years} years"
        return (
            f"I'm a {(config.profile.headline or 'software engineer').strip()} with "
            f"{years_label} of experience building production "
            f"software across {(', '.join(str(s) for s in config.profile.core_skills[:4]) or 'modern web stacks')}. "
            f"{target.capitalize()}{at_company} fits the end-to-end product work I enjoy, and I'd bring "
            "the same ownership to building and shipping features with your team."
        )

    if re.search(r"cover letter|additional information|anything else|about you|summary|introduce", q, re.I):
        return _profile_snippet(config)

    if re.search(r"okay for|comfortable with|willing to work|work from office|\bwfo\b|relocat", q, re.I):
        return "Yes, I'm comfortable with that location and working from the office."

    if re.search(r"availability|notice period|when can you join|joining time|how soon", q, re.I):
        try:
            days = int(facts.get("notice_period_days") or 0)
        except (TypeError, ValueError):
            days = 0
        return "Immediately" if days == 0 else f"{days} days"

    return None


def _numeric_guess(question: str, field: dict[str, Any], config: AppConfig) -> str | None:
    input_type = str(field.get("input_type", "")).lower()
    group = classify_question(question)

    try:
        facts = load_application_facts(config)
    except Exception:
        facts = {}

    if input_type == "pincode":
        pincode = str(facts.get("pincode", "")).strip()
        return pincode or None

    if input_type == "years_numeric":
        if group.startswith("skill:"):
            years = _skill_years(config, question)
            # Unknown/unlisted skill → 0 is the honest, low-risk guess.
            return str(years) if years is not None else "0"
        return str(int(config.profile.years_experience or 0))

    if input_type == "ctc_numeric":
        return format_lpa(config.compensation.expected_ctc_lpa)

    if input_type == "date":
        if group in ("desired_start_date", "notice_period", "join_availability"):
            days = 0
            try:
                days = int(facts.get("notice_period_days") or 0)
            except (TypeError, ValueError):
                days = 0
            target = date.today() + timedelta(days=max(0, days))
            return target.strftime("%d/%m/%Y")
        return None

    if input_type == "number":
        if re.search(r"report|team size|people", question, re.I):
            return "0"
    return None


def guess_answer(
    config: AppConfig,
    question: str,
    field: dict[str, Any] | None = None,
    *,
    job: Any = None,
) -> str | None:
    """Best-effort answer for one screening question, or None if unsafe to guess."""
    q = str(question or "").strip()
    if not q or _NEVER_GUESS.search(q):
        return None
    if classify_question(q) in ("pan", "uan"):
        return None

    enriched = enrich_field_for_llm(field or {"label": q})
    kind = str(enriched.get("kind", "text")).lower()
    input_type = str(enriched.get("input_type", "")).lower()

    if kind in _CHOICE_KINDS or (len(_options(enriched)) >= 2 and input_type not in {"ctc_numeric", "years_numeric"}):
        return _pick_option(q, enriched, config, job)

    numeric = _numeric_guess(q, enriched, config)
    if numeric is not None:
        return numeric

    if kind in ("text", "textarea", "input", "contenteditable") or input_type in {"short_text", "long_text"}:
        if kind not in ("text", "textarea", "input", "contenteditable"):
            return None
        return _free_text_guess(q, config, job)

    return None
