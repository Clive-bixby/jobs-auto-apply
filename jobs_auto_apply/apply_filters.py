"""Shared job-list filtering before apply."""

from __future__ import annotations

import logging

from .config import AppConfig
from .job_selection import load_applied_companies
from .limits import apply_cap
from .role_filter import filter_no_experience_roles, filter_skipped_roles, role_filter_kwargs
from .run_issues import run_attempted_job_keys
from .salary import combined_salary_text, is_salary_eligible, wellfound_salary_floor
from .utils import JobListing, company_key, filter_skipped_companies, job_key

logger = logging.getLogger("job_apply")


def _known_experience_skills(config: AppConfig) -> list[str]:
    """Skills the candidate has — core_skills plus skill_years entries above 0.

    Used as the keep-guard so a no-experience-skill title is only skipped when it
    does not also name a skill we actually have.
    """
    known = [s for s in config.profile.core_skills if str(s).strip()]
    try:
        from .profile.application_facts import load_application_facts

        app_facts = load_application_facts(config)
        skill_years = app_facts.get("skill_years")
        if isinstance(skill_years, dict):
            for name, years in skill_years.items():
                try:
                    if float(str(years).strip()) > 0:
                        known.append(str(name).replace("_", " "))
                except (TypeError, ValueError):
                    continue
    except Exception:
        pass
    return known


def _salary_floor(config: AppConfig, job: JobListing) -> tuple[float, bool]:
    """Effective (floor, require_listed) for a job's platform."""
    if job.source == "wellfound":
        return wellfound_salary_floor(config)
    floor = config.application.min_inr_salary_lpa
    if job.source == "naukri":
        filters = getattr(getattr(config, "naukri", None), "filters", None)
        lakhs = getattr(filters, "salary_min_lakhs", None)
        if lakhs:
            floor = max(floor, float(lakhs))
    return floor, False


def filter_one_per_company(jobs: list[JobListing], config: AppConfig) -> list[JobListing]:
    """Keep one opening per company, and none at companies already applied to.

    Jobs with no known employer are kept individually — the caller may not have
    enriched them yet (Hirist cards carry no company name).
    """
    if not config.application.one_job_per_company:
        return jobs
    applied_companies = load_applied_companies(config.applied_jobs_path)
    kept: list[JobListing] = []
    seen: set[str] = set()
    skipped_applied = 0
    skipped_dupe = 0
    for job in jobs:
        key = company_key(job.company)
        if not key:
            kept.append(job)
            continue
        if key in applied_companies:
            skipped_applied += 1
            logger.info("Skipping %s @ %s — already applied to this company", job.title, job.company)
            continue
        if key in seen:
            skipped_dupe += 1
            logger.info("Skipping %s @ %s — one job per company already queued", job.title, job.company)
            continue
        seen.add(key)
        kept.append(job)
    if skipped_applied:
        logger.info("Skipped %d job(s) at companies already applied to", skipped_applied)
    if skipped_dupe:
        logger.info("Skipped %d duplicate-company job(s)", skipped_dupe)
    return kept


def filter_pending_jobs(
    jobs: list[JobListing],
    applied_ids: set[str],
    limit: int,
    config: AppConfig,
) -> list[JobListing]:
    pending: list[JobListing] = []
    attempted_this_run = run_attempted_job_keys()
    skipped_attempted = 0
    skipped_applied = 0
    filtered = filter_skipped_roles(
        filter_skipped_companies(jobs, config.profile.skip_companies),
        **role_filter_kwargs(config.profile),
    )
    filtered = filter_no_experience_roles(
        filtered,
        no_exp_skills=config.profile.skip_no_experience_skills,
        known_skills=_known_experience_skills(config),
    )
    if config.application.skip_ineligible_salary:
        kept: list[JobListing] = []
        skipped_salary = 0
        for job in filtered:
            min_lpa, require_salary = _salary_floor(config, job)
            eligible, reason = is_salary_eligible(
                combined_salary_text(jd=job.description, meta=job.meta),
                min_inr_lpa=min_lpa,
                require_listed_salary=require_salary,
            )
            if eligible:
                kept.append(job)
            else:
                skipped_salary += 1
                logger.info(
                    "Skipping salary-ineligible: %s @ %s — %s",
                    job.title,
                    job.company,
                    reason,
                )
        filtered = kept
        if skipped_salary:
            logger.info(
                "Skipped %d job(s) below the %g LPA floor",
                skipped_salary,
                config.application.min_inr_salary_lpa,
            )
    filtered = filter_one_per_company(filtered, config)
    for job in filtered:
        key = job_key(job.source, job.job_id)
        if key in applied_ids:
            skipped_applied += 1
            continue
        if key in attempted_this_run:
            skipped_attempted += 1
            continue
        pending.append(job)
        cap = apply_cap(limit)
        if cap is not None and len(pending) >= cap:
            break
    if skipped_applied:
        logger.info(
            "Skipped %d job(s) already applied or deferred this run",
            skipped_applied,
        )
    if skipped_attempted:
        logger.info(
            "Skipped %d job(s) already attempted this run",
            skipped_attempted,
        )
    return pending
