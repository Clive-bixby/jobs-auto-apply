# Handoff — jobs-auto-apply (5 portals)

Written 2026-10-22. Give this file to the next coding agent.

## Where things live

- **Repo:** `D:\jobs-auto-apply` (moved from `C:\Users\Aryan Yadav\Documents\Default Project` on 2026-10-22; the old path is deleted).
- **Venv:** `D:\jobs-auto-apply\.venv` (Python 3.13). It survived the move — `python.exe -m` works; `Scripts\pip.exe` paths are stale, use `python -m pip`.
- **Upstream:** clone of `https://github.com/abhayiitbhu/jobs-auto-apply`.
- **Git:** repo is dirty (all fixes below are uncommitted). No commit/push has been made.

## Goal

Auto-apply to jobs on **Naukri, Hirist, Instahyre, Wellfound, Uplers** using the user's
real logged-in Chrome profile (`Profile 1`, aryansecondmail@gmail.com). LinkedIn is not a
supported platform. No local LLM (Ollama disabled).

## How to run

```powershell
cd D:\jobs-auto-apply
# Chrome must be CLOSED first (the automation reuses the real profile).
.\run.cmd run --platform naukri
# or
.\.venv\Scripts\python.exe main.py run --platform all
```

`main.py --help` for commands: `run`, `review`, `apply-reviewed`, `answer-questions`,
`login`, `verify`, `chrome-profiles`, `serve`.

Exit code is **1 when nothing was applied** — that is normal, not a crash.

## Identity / answer facts

- `profile/application_facts.yaml` — the source of truth for screening answers.
  - notice 0 days, can join immediately; `f2f_interview_available`/`interview_available` Yes;
    `has_laptop: true`; pincode 122011 (Gurgaon); willing to relocate Yes;
    skills (all 1 yr) and no-experience skills (java, php, dotnet, angular, flutter, …).
  - Deliberately blank → questioned: `pan`, `uan`, `gender`, `date_of_birth`, `cgpa`, `percentage`.
- `config.yaml` (gitignored) — all runtime settings. `profile/`, `resume.pdf`, `data/sessions/`,
  `browser-data/` are gitignored. Never commit cookies, sessions, or the personal Chrome profile.
- Compensation: current CTC 0, expected 8 LPA, `include_ctc: false`.

## Current config values that matter

| Setting | Value | Why |
|---|---|---|
| `application.dry_run` | `false` | live applies; set `true` to rehearse |
| `application.max_jobs_per_run` | 3 | per-run cap (lower it for quick checks) |
| `application.apply_workers` | 3 | parallel tabs (Wellfound); Naukri uses its own `naukri_apply_workers` |
| `application.naukri_apply_workers` | **1** | Naukri's chatbot is one per-user session; parallel tabs interleave answers and corrupt fills |
| `naukri.filters.keywords` | `"full stack developer"` | the old 8-term AND slug returned 1–6 listings; broad term returns 20 |
| `naukri.filters.experience_max` | 2 | entry level |
| `naukri.filters.max_job_age_days` | 7 | |
| `naukri.filters.max_pages` | 5 | scroll batches |
| `auth.login_timeout_seconds` | 300 | manual login window |
| `chrome_user_data_dir` | `""` | `""` = real Chrome user data dir |
| `chrome_profile_name` | `"Profile 1"` | |
| `resume.sync_to_naukri` | false | visiting the profile page logs the automated session out |
| `application.apply_retries` | 0 | avoids double-applying when confirmation is ambiguous |
| `application.interactive_questions` | false | unknown questions are queued, never guessed |
| `profile.skip_role_keywords` | includes `designer`, `customer experience` | keeps Instahyre's unfiltered search from applying to non-engineering roles |

## Verified results so far

All of these were re-checked on the live sites after the run (not just logged by the tool).

| Portal | Applications | Where |
|---|---|---|
| Naukri | 11 | Forward Eye, Xomiro, Doctutorials, Techknomatic, Bloom Cap, Trijit, Softobiz, Krishna's Herbal & Ayurveda, 3× Infosys |
| Wellfound | 5 | Parsewave, Babaclick Trading, Securelytix, Auroscale, Variabl |
| Hirist | 4 | Tracxn, Yoda Technologies, SquadStack.ai, RBHU Analytics |
| Uplers | 3 | AA, Max Digital, Synergy Tech — each shows "Application Under Review" |
| Instahyre | 1 | Software Development Engineer II @ HighLevel — `Applied jobs` 43 → 44, API `status: 1` |

Naukri had recorded several applications as *technical failures* because of a confirmation
race (see below). `scripts/reconcile_naukri_applied.py` re-checked every failure live, marked
the 11 as applied, and cleared their false failure entries.

`data/technical_failures.json` holds 4 Naukri entries from the confirmation race; they are
harmless once reconciled (run `scripts/reconcile_naukri_applied.py`).

## Code changes (all uncommitted)

### `jobs_auto_apply/uplers/apply.py` — rewritten
Replaced the dead external-ATS resolver with the in-platform flow:

1. Close any open drawer, find the card by job id (`.jobCard:has(#skills_<ID>)`, falling back to
   `.jobCard:has(.uplersPartnerBadge#partner<ID>)`), scrolling the feed up to 6 screens.
2. Click the card → detail drawer → `button.applyBtn` ("APPLY NOW") → `form#apply-form`.
3. Fill: years/months from `profile.years_experience`, `#current_ctc` (0 is accepted here),
   `#expected_ctc` (8), last working day = today (required even for an immediate joiner),
   preferred mode of work = Remote (react-select, optional), shift question = Yes.
4. Submit `input[type=submit][value="Apply Now"]`; success = the form detaches. If it stays
   open, visible error text is logged and the job is a failure.
5. Save the applied key (`uplers:<id>`).

### `jobs_auto_apply/instahyre/` — search feed + apply
- `feeds.py`: new `_ui_open_search_tab()`. The account's matching feed is empty
  (`status_counts {"0":0,"1":43,"2":9}`), but the **Search** tab has 12,590 jobs. Direct
  navigation to `?search=true` is rewritten to `?matching=true`, so the tab must be clicked.
  Legacy `#job-search-section` filters are applied only when that panel exists; otherwise the
  run proceeds with the unfiltered result set.
- `search.py`: `VIEW_BUTTON` / `click_view_at` now know `button.btn-interested` (live DOM).
- `apply.py`:
  - `APPLY_MODAL` is now exactly `.application-modal.candidate-apply-modal`. The old broader
    selector matched a **different** panel (the employer profile block), so every apply looked
    like "no apply button".
  - `_visible_apply_button()` scans every match for the first *visible* Apply control, with a
    `button.btn-primary.new-btn` fallback that excludes "Apply on company site".
  - `apply_feed()` rewritten: pick the first row passing the role/company filters
    (`_first_acceptable_row`), click View, apply, close, repeat until the cap. No more
    `ArrowRight` chain through unrelated jobs.
  - `apply_feed` saves the application with the row's title/company.

### `jobs_auto_apply/uplers/search.py`
- Stale mobile selector `div.jobCardMobile` → `div.jobCard` (the live DOM).
- Job id now comes from the card's `id`, else `.uplersPartnerBadge#partner<ID>`, else
  `#skills_<ID>`; cards have no `id` of their own any more.
- Removed the `if partnered: continue` guard — every current card has the partner badge, so
  it discarded 100 % of listings.
- Title selector `.jobTitle .content h6` → `.jobTitle .main h6` with fallbacks.
- `apply_filters` no longer types each skill into the same search box after the keywords
  (the last skill used to overwrite the query and return 0 jobs).

### `jobs_auto_apply/uplers/auth.py`
- `LOGGED_IN_SELECTOR` → `div.jobCard, div.opportunityList .jobCard`.

### `jobs_auto_apply/naukri/search.py`
- Removed the over-broad `a[href*="-jobs-"]` selector. It matched Naukri SEO/company pages
  (`/mean-stack-developer-jobs-in-pune`, `/techknomatic-jobs-careers-123`), which produced
  ~106 fake "jobs" with garbage titles.
- Added `_is_job_listing_url()` — only `/job-listings-<slug>-<digits>` is a real detail page.
- Result: 106 junk → 6 real listings on the same search.

### `jobs_auto_apply/naukri/apply.py`
- Naukri's job-detail page was redesigned: `#jobs-desc` is gone and the button is
  `button#apply-button` (`.apply-button`) with the label **"Apply"**, not "Quick apply".
  - `_AURUS_APPLY_STATE_JS` understands the new button and the `.already-applied` label.
  - `_find_quick_apply_button` falls back to `#apply-button` / `.apply-button` filtered by
    `_PRIMARY_APPLY_RE` (exact "Apply" / "Quick apply", so "Applied" doesn't match).
- `.already-applied` (class `styles_already-applied__*`) is the reliable applied marker.
- Added `_naukri_company_site_apply()`: jobs whose primary action is "Apply on company site"
  are skipped as `abandoned` instead of recorded as failures.
- Confirmation hardening: after the chatbot closes, reload the page up to 3× and wait for
  `.already-applied` (server-side propagation lags a few seconds).

### `jobs_auto_apply/naukri/questions.py`
- `_log_chatbot_reply()` — logs the chatbot's reply after sending an answer.
- `_click_chatbot_skip()` — clicks the chatbot's "Skip this question" control.
- `_answer_is_zero()` + current-CTC rule: Naukri rejects `0` as current CTC
  ("The input seems invalid"). Click Skip and return — **do not fall through** to the text
  fill, or the `0` lands in the *next* question (observed).
- `_advance_after_choice()` — after clicking a chip/radio, if the question doesn't advance,
  click the panel's Save button and poll again.

### `jobs_auto_apply/question_groups.py`
- `interview_availability` gained `available.{0,40}interview` and `interview.{0,25}available`
  patterns (the label "Are you available for a interview?(Virtual)" was falling through to a
  `unique:` bucket).
- New `has_laptop` group (`\blaptop\b`).

### `jobs_auto_apply/answers/config_answers.py`
- `f2f_interview_answer` now covers both `f2f_interview` and `interview_availability`, and
  prefers `interview_available` over `f2f_interview_available`.
- New `laptop_answer` (Yes/No from `application_facts.has_laptop`), wired into
  `authoritative_config_answer`.

### `jobs_auto_apply/hirist/apply.py`
- The step loop now re-checks the live applied state at the start of steps 2+ and again
  before recording a "could not fill answered field(s)" technical failure. Hirist submits on
  step 1, briefly re-renders the same screening questions, then flips the job page to
  "Applied"; the old code recorded a false failure in that window (RBHU Analytics).

### Earlier upstream fixes
- `requirements.txt`: added `dataclasses-jsonschema` (the clone was broken without it).
- Rebuilt the missing `jobs_auto_apply/profile/` package.
- `.gitignore`: `profile/` → `/profile/` so the package is tracked.
- `chrome_profile.py`, `browser.py`, `cli.py`: support for the real Chrome profile
  (`chrome_user_data_dir: ""`) + lock checks; dedicated-profile mode still available.
- `run.cmd`: wrapper that runs the venv python.

### New scripts
- `scripts/check_browser_profile.py` — verifies the resolved Chrome profile.
- `scripts/open_login_browser.py` — opens Chrome on the automation profile for manual login.
- `scripts/reconcile_naukri_applied.py` — **run after Naukri runs**: visits each technical
  failure's detail page, marks `.already-applied` ones as applied and clears the failure.

## Known limitations / gotchas

- **Naukri blocks headless** ("Access Denied"). All browser work is headed with
  `channel="chrome"`.
- **Confirmation is racy on Naukri.** A submitted application can still be logged as a
  technical failure. Always run the reconcile script; treat `data/technical_failures.json` as
  a hint, not truth.
- **Current CTC 0** is rejected by Naukri → the question is skipped. Uplers **accepts** 0.
- **"Apply on company site"** jobs cannot be auto-filled on Naukri; they are skipped and
  recorded as `abandoned`, so they don't reappear.
- **Uplers requires a last working day** even with "Immediately" selected; the code sends
  today's date (notice period is 0).
- **Instahyre's search results are unfiltered** (12,590 jobs sorted by relevance, seniority
  first). Role filtering happens client-side in `_first_acceptable_row`; that is why
  `designer` / `customer experience` were added to `skip_role_keywords`.
- **Pending questions:** only 2 Naukri groups remain, and both are the user's call (they left
  them unanswered): "What is your current employment status?" and "Are you comfortable in
  working permanent remote setup?". Everything else is answered in `data/user_memory.json`
  (laptop Yes, virtual interview Yes, current CTC 0, Hirist discipline/marks).
  Answer with `main.py answer-questions` (interactive), or via
  `jobs_auto_apply.answers.memory_store.save_answer`, then re-run `--platform naukri`.
- `load_config()` takes a `Path`, not a `str`.
- Importing `jobs_auto_apply.rag_answers` directly hits a circular import; import
  `jobs_auto_apply.answers.draft` first.
- `config.yaml` in this session was written with `Set-Content -Encoding utf8` (adds a BOM);
  it parses fine, but a BOM once made `pending_questions.json` invalid.

## Platform verdicts

Tested 2026-10-22 on the real `Profile 1` Chrome profile. All runs were headed.
Every application below was re-opened on the live site afterwards.

| Platform | Discovery | Apply | Verdict |
|---|---|---|---|
| **Naukri** | ✅ 20 listings | ✅ 11 real applications submitted + verified | **Production ready** |
| **Wellfound** | ✅ 5 listings, JD from `__NEXT_DATA__` | ✅ 5/5 applied live | **Working** |
| **Hirist** | ✅ 6 feeds crawled, role filter works | ✅ 4/4 applied live | **Working** |
| **Uplers** | ✅ after fix | ✅ 3/3 applied live via in-platform modal | **Working** |
| **Instahyre** | ✅ Search tab, 12,590 jobs | ✅ 1/1 applied live, count 43 → 44 | **Working (search feed)** |

### Wellfound — working

```
Feed scroll complete — 5 listings discovered
[w3] Applied to Backend Engineer @ Securelytix
[w2] Applied to Full-Stack Engineer (AI) @ Variabl
[w1] Applied to Full Stack Engineer Intern @ Auroscale
Pipeline finished: 3 applied, 0 skipped, 0 failed
```

No code changes were needed for Wellfound.

### Hirist — working

```
[1/2] Tracxn - Backend Developer            -> Applied on Hirist
[2/2] Yoda Technologies - Full Stack ...    -> Applied on Hirist
Parallel apply finished: 2/2 succeeded (5 workers)
```

Later runs added SquadStack.ai and RBHU Analytics. RBHU's page shows the disabled
**"Applied"** button; the run had logged a false technical failure because the app submits on
step 1 and then briefly re-renders the questions — fixed in `hirist/apply.py` (see above).
Cosmetic issue only: the company column is empty in the run table (Hirist cards no longer
expose a company name in the parsed selector).

### Uplers — working

```
Applied on Uplers: Full Stack Developer @ Max Digital
Applied on Uplers: Full Stack Developer @ Synergy Tech
```

All three show **"Application Under Review"** and *"Congratulations! Your application has
been successfully received."* on `https://platform.uplers.com/talent/my-opportunities`.

Notes if it breaks again:
- `?activeJob=<ID>` does **not** render the detail on direct navigation — the card must be
  clicked.
- Required fields are current CTC and last working day; without them the modal never closes.
- The drawer has both `button.applyBtn` ("APPLY NOW") and a plain `button.primaryBtn`
  ("Apply"); use `.applyBtn` first.
- The shift question is job-specific (e.g. "7:30am to 4:30pm IST"); answer Yes.
- "Preferred mode of work" is an optional react-select; the code picks "Remote".

### Instahyre — working via the Search feed

The matching feed is still empty for this account (`fetch_navbar_count: 0`), and that is a
site/account condition, not a bug. The fix is to use the Search tab:

```
Instahyre search view opened
Instahyre search filters UI not present; using unfiltered search results
Employer rows loaded: 30
Applied on Instahyre: Software Development Engineer II @ HighLevel
```

Verification: `Applied jobs` went 43 → 44, and
`/api/v1/candidate_opportunities/candidate_matching?...&interest_facet=1` lists
"Software Development Engineer II" with `status: 1` at `2026-10-22T11:57:28+00:00`.

Two traps are documented above: the modal selector must be
`.application-modal.candidate-apply-modal` (not `.apply-modal`), and the Apply button is
`button.btn-primary.new-btn` (there is also "Apply on company site" for external jobs, which
must not be clicked).

## Next steps (in priority order)

1. **Answer the 2 deferred Naukri questions** (employment status, permanent remote), then
   re-run `--platform naukri` to pick up the jobs that were skipped.
2. Decide the steady-state `max_jobs_per_run` (3 now). Raise it for volume runs; lower it to 1
   when validating a new portal.
3. Optional cleanup: remove the stale Naukri entries from `data/technical_failures.json` after a
   successful reconcile, and delete the temporary `_probe_*` / `_verify_*` artifacts at the repo
   root.
4. `main.py run --platform all` is now safe for all five portals.

## Files left behind (deliberately)

- `data/run.log` — full UTF-8 log of all runs, including the platform test.
- `data/platform_test.log` — the dry-run batch log. **It is UTF-16LE** (PowerShell `*>>`
  redirection), so read it with `Get-Content -Encoding Unicode`; `run.log` is easier.
- `config.yaml` — live mode (`dry_run: false`), cap 3, Uplers keywords `"full stack developer"`.
