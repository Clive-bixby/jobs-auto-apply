"""Skill-years lookups shared by the answer engine.

Resolution order for "how many years of X": explicit ``skill_years`` in
application_facts.yaml, then ``skill_years == 0`` (means "none"), then the
resume / ``profile.core_skills``. Only a declared year wins outright; an
undeclared skill that merely appears in the resume falls back to
``profile.years_experience``.
"""

from __future__ import annotations

import re
from typing import Any

from ..config import AppConfig
from ..profile_data import ResumeFacts, build_resume_context, load_resume_facts
from .application_facts import load_application_facts

# Common shorthands recruiters use that should hit the same skill_years key.
_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "node": "nodejs",
    "node.js": "nodejs",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "plsql": "oracle",
    "rest": "rest apis",
    "rest api": "rest apis",
    "restful api": "rest apis",
    "restful apis": "rest apis",
    "springboot": "spring",
    "spring boot": "spring",
    "ml": "machine learning",
    "ai": "machine learning",
    "genai": "ai_ml",
    "gen ai": "ai_ml",
    "llm": "ai_ml",
    "sci kit learn": "sklearn",
    "scikit learn": "sklearn",
}


def _norm(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace ('REST_APIs' -> 'rest apis')."""
    cleaned = re.sub(r"[^a-z0-9+#. ]+", " ", (text or "").lower().replace("_", " "))
    return re.sub(r"\s+", " ", cleaned).strip()


def _canonical(skill: str) -> str:
    norm = _norm(skill)
    return _ALIASES.get(norm, norm)


def _declared_years(app_facts: dict[str, Any]) -> dict[str, int]:
    raw = app_facts.get("skill_years")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        try:
            out[_canonical(str(key))] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def skill_years_override(app_facts: dict[str, Any], skill: str) -> int | None:
    """Explicit years for a skill from application_facts.skill_years, else None."""
    return _declared_years(app_facts).get(_canonical(skill))


def _resume_skill_names(facts: ResumeFacts) -> set[str]:
    names: set[str] = set()
    for items in (facts.technical_skills or {}).values():
        for item in items or []:
            # "Java (Spring Boot)" -> java, spring boot
            for part in re.split(r"[,()/]| and ", str(item)):
                norm = _canonical(part)
                if norm:
                    names.add(norm)
    return names


def _resume_text(facts: ResumeFacts) -> str:
    return _norm(build_resume_context(facts))


def has_skill(
    facts: ResumeFacts,
    skill: str,
    config: AppConfig | None = None,
    app_facts: dict[str, Any] | None = None,
) -> bool:
    """True when the skill is declared, configured, or present in the resume."""
    override = skill_years_override(app_facts or {}, skill)
    if override is not None:
        return override > 0
    canonical = _canonical(skill)
    if not canonical:
        return False
    if config is not None and canonical in {_canonical(s) for s in config.profile.core_skills}:
        return True
    return canonical in _resume_skill_names(facts) or canonical in _resume_text(facts)


def skill_experience_configured(
    config: AppConfig,
    facts: ResumeFacts,
    app_facts: dict[str, Any],
    skill: str,
) -> bool:
    """True when we can answer "years of X" for this skill without the LLM."""
    return skill_years_override(app_facts, skill) is not None or has_skill(facts, skill, config, app_facts)


def skill_years_answer(
    config: AppConfig,
    facts: ResumeFacts,
    app_facts: dict[str, Any],
    skill: str,
) -> str | None:
    """Years to report for a skill, or None when the skill is unknown (defer)."""
    override = skill_years_override(app_facts, skill)
    if override is not None:
        return str(override)
    if has_skill(facts, skill, config, app_facts):
        return str(config.profile.years_experience)
    return None


def load_skill_context(config: AppConfig) -> tuple[ResumeFacts, dict[str, Any]]:
    """Resume facts + application facts, the pair every skill lookup needs."""
    return load_resume_facts(config.base_dir), load_application_facts(config)


def resume_blob(facts: ResumeFacts, config: AppConfig | None = None) -> str:
    """Normalized resume text for keyword/substring matching (core skills included)."""
    parts = [build_resume_context(facts)]
    if config is not None:
        parts.append(" ".join(str(s) for s in config.profile.core_skills))
    return _norm(" ".join(parts))
