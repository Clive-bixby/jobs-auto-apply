"""Last-resort answer for a question nothing else could answer.

Fills from profile facts, a matching field option, or a sane default, so an
unknown question never blocks an application. Deterministic and not persisted:
it is re-derived per run, so a wrong guess never becomes saved memory.

ponytail: heuristic guess, not verified truth - ``llm.enabled`` supersedes it
once Ollama models are pulled.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..config import AppConfig
from .fields import infer_field_input_type
from .labels import is_why_company_question
from .validation import requires_personal_artifact

_YEARS_BAR = re.compile(r"(\d+)\s*\+?\s*years?")
_YES_NO = re.compile(r"^\s*(yes|no)\b", re.I)


def _option_matches_years(option: str, years: int) -> bool:
    text = str(option)
    lo_hi = re.match(r"^\s*(\d+)\s*(?:-|to)\s*(\d+)", text)
    if lo_hi:
        return int(lo_hi.group(1)) <= years <= int(lo_hi.group(2))
    below = re.match(r"^\s*<\s*(\d+)", text)
    if below:
        return years < int(below.group(1))
    above = re.match(r"^\s*(\d+)\s*\+", text)
    if above:
        return years >= int(above.group(1))
    return str(years) in text


def fallback_answer(
    config: AppConfig,
    label: str,
    field: dict[str, Any],
    *,
    company: str = "",
    job_title: str = "",
) -> str | None:
    """Predict an answer from the data present. ``None`` = still defensible to defer."""
    question = str(label or "").strip()
    if not question:
        return None
    low = question.lower()

    input_type = str(field.get("input_type") or "") or infer_field_input_type(question, field)
    options = [
        str(o).strip()
        for o in (field.get("options") or field.get("answer_options") or [])
        if str(o).strip()
    ]
    years = int(getattr(config.profile, "years_experience", 1) or 0)

    asked = _YEARS_BAR.search(low)
    # "Do you have 4+ years of X?" - the bar sits above what we actually have.
    bar = int(asked.group(1)) if asked else None
    honest_no = bar is not None and bar > years

    candidates: list[str] = []

    if requires_personal_artifact(question):
        # Real links from the config beat an invented one.
        link = str(config.user.github or config.user.linkedin or "").strip()
        if link:
            candidates.append(link)

    if options and (input_type in {"single_choice", "yes_no_checkbox", "multi_choice"} or len(options) <= 6):
        if {o.lower() for o in options} <= {"yes", "no"}:
            candidates.append("No" if honest_no else "Yes")
        else:
            picked = next((o for o in options if _option_matches_years(o, years)), None)
            if picked is None and "Yes" in options:
                picked = "No" if honest_no else "Yes"
            candidates.append(picked or options[0])

    if input_type in {"years_numeric", "number", "ctc_numeric"} or (asked and input_type == "short_text"):
        if not honest_no:
            candidates.append(str(years))
    elif re.search(r"^\s*(is|are|do|does|did|can|could|would|will|have|has|had|would you|are you)\b", low):
        candidates.append("No" if honest_no else "Yes")
    elif "gap" in low:
        candidates.append("No")

    if input_type == "date" and re.search(r"start|join|available|notice|joining", low):
        candidates.append(date.today().isoformat())

    if input_type == "location":
        location = str(
            (getattr(config, "application_facts", None) or {}).get("current_location", "")
            or config.profile.locations[0]
        ).strip()
        if location:
            candidates.append(location)

    if input_type in {"short_text", "long_text", "text", "contenteditable"}:
        if is_why_company_question(question):
            who = company or "your team"
            candidates.append(f"I want to build your product as a full-stack engineer and grow with {who}.")
        else:
            candidates.append(
                "1 year of hands-on work with React, Node.js and Python; details are in my resume."
            )

    for candidate in candidates:
        text = str(candidate).strip()
        if text:
            return text
    return None