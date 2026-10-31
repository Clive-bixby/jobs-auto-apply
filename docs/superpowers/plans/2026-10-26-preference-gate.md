# Preference Gate + Speed/Volume Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the bot apply only to roles that clear an 8 LPA floor and match the configured target roles, while cutting wasted per-job work and raising qualified volume.

**Architecture:** Keep the existing Playwright pipeline. Make the existing config keys live (`target_roles`, `salary_min`, `include_no_salary`, `salary_min_lakhs`), add one explicit positive role gate (`profile.require_role_keywords`), change salary eligibility to use the lower bound of a range, and normalize two recurring screening questions so jobs are not dropped.

**Tech Stack:** Python 3.10+, Playwright, PyYAML, unittest.

**Spec:** Approved design in the 2026-10-26 conversation (short design: preference gate, question fixes, speed/volume).

## Global Constraints

- Salary floor: `8` LPA, measured against the **lower** bound of a listed INR range.
- No-salary jobs: allowed by default; skipped on Wellfound when `include_no_salary: false`.
- Positive role gate is opt-in via `profile.require_role_keywords`; empty means off.
- Naukri keeps `naukri_apply_workers: 1` (chatbot safety).
- `one_job_per_company` stays `true`.
- Do not touch Obscura, the browser layer, or the LLM.
- Repo is dirty. Do not commit unrelated work.

## Review Focus

- A range like `₹6L–₹12L` must fail an 8 LPA floor even though its top clears it.
- A title that matches a target role but also a skip rule (e.g. `Senior Full Stack Engineer`) must be skipped.
- `Full Stack Developer Intern` must be skipped even though it matches `Full Stack Developer`.
- A saved answer `Can Relocate All Over India` must fill a Yes/No radio as `Yes`.
- `How many years of experience do you have in total?` must answer `1`, not defer.

---

### Task 1: Salary floor uses the lower bound

**Files:**
- Modify: `jobs_auto_apply/salary.py`
- Test: `tests/test_preferences.py`

**Interfaces:**
- Produces: `is_salary_eligible(text, *, min_inr_lpa=25.0, require_listed_salary=False) -> tuple[bool, str]`
- Produces: `SalaryRange.min_inr_lpa -> float`
- Produces: `wellfound_salary_floor(config) -> tuple[float, bool]`

- [x] Add `min_inr_lpa` property to `SalaryRange`.
- [x] Add `require_listed_salary` through `is_salary_eligible`, `eligibility_summary`, `job_eligibility`, `is_job_salary_eligible`.
- [x] Gate on `min(r.min_inr_lpa for INR ranges) >= min_inr_lpa`.
- [x] Add `wellfound_salary_floor(config)` returning `(floor, require_listed_salary)` from `wellfound.filters.salary_min` / `include_no_salary`.
- [x] Test: `₹6L–₹12L` fails at 8; `₹8L–₹12L` passes; no salary passes by default and fails when required.

### Task 2: Positive role gate + skip rules

**Files:**
- Modify: `jobs_auto_apply/config.py`, `jobs_auto_apply/role_filter.py`, `jobs_auto_apply/apply_filters.py`
- Test: `tests/test_preferences.py`

**Interfaces:**
- Produces: `ProfileConfig.require_role_keywords: list[str]`
- Produces: `should_skip_role(..., require_keywords: list[str] | None = None)`
- Produces: `filter_skipped_roles(..., require_keywords=None)`
- Produces: `auto_reject_skipped_roles(..., require_keywords=None)`

- [x] Add `require_role_keywords` to `ProfileConfig` and `_profile_config`.
- [x] Include it in `role_filter_kwargs`.
- [x] After skip rules, skip when `require_keywords` is non-empty and the title matches none.
- [x] Add a shared salary gate to `filter_pending_jobs` using the lower-bound floor.
- [x] Test: target role passes; `SDET` fails; intern fails; senior target role fails.

### Task 3: Wellfound honors config salary/no-salary

**Files:**
- Modify: `jobs_auto_apply/wellfound/apply.py`, `jobs_auto_apply/wellfound/pipeline.py`, `jobs_auto_apply/wellfound/modal.py`, `jobs_auto_apply/cli.py`, `jobs_auto_apply/review.py`

- [x] Use `wellfound_salary_floor(config)` at every Wellfound salary check.
- [x] Pass `require_listed_salary` through `job_eligibility` / `eligibility_summary`.
- [x] Leave the feed-level quick skip conditional on a parsed card range; the enriched check handles missing salary.

### Task 4: Question fixes

**Files:**
- Modify: `jobs_auto_apply/question_groups.py`, `jobs_auto_apply/answers/config_answers.py`, `jobs_auto_apply/answers/memory_store.py`, `jobs_auto_apply/naukri/questions.py`, `data/user_memory.json`

- [x] Add total-experience patterns (`in total`, `total years of experience`).
- [x] Add `total_experience_answer` returning `profile.years_experience` and wire it into `authoritative_config_answer`.
- [x] Map positive relocation phrases to `Yes` for Yes/No options in `memory_store` and `naukri/questions`.
- [x] Update `preferred_location:yesno` saved answer to `Yes`.

### Task 5: Config

**Files:**
- Modify: `config.yaml`, `config.example.yaml`

- [x] `application.min_inr_salary_lpa: 8`
- [x] `application.max_jobs_per_run: 25`
- [x] `application.parallel_platforms: true`
- [x] `naukri.filters.quick_apply_only: true`
- [x] `wellfound.filters.use_profile_filters: false`, `salary_min: 800000`, `include_no_salary: false`
- [x] Add `profile.require_role_keywords` (target roles) and the intern/seniority skip rules.
- [x] Document the new keys in `config.example.yaml`.

### Task 6: Verify

- [x] `python -m unittest discover -s tests -v`
- [x] `python -m compileall jobs_auto_apply`
- [x] Load `config.yaml` and print the effective floor, require-role list, and caps.
- [x] `ruff check jobs_auto_apply tests` if available.
