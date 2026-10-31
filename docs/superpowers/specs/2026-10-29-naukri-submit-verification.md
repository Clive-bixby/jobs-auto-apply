# Naukri submit verification: submit works, confirmation did not

**Date:** 2026-10-29
**Status:** resolved

## Question

The 2026-10-29 report's #1 action was: does the Naukri apply flow actually
confirm a submit? Run 8 (`data/run-20261026h.log`) logged 14
`Could not confirm Naukri apply` warnings, and no Naukri application had been
recorded as `applied` since 2026-10-23.

## Evidence

### 1. The failures were all chatbot flows

All 14 warnings in run 8 read
`Naukri apply not confirmed (chatbot closed)`. Every one followed a chatbot
questionnaire. `data/technical_failures.json` held 37 Naukri failures; 28 were
genuine apply attempts and 9 were `net::ERR_NE*` navigation errors.

### 2. Most "failures" were actually applied

`scripts/reconcile_naukri_applied.py --limit 10` then the full pass checked every
failed job's detail page for `.already-applied`:

- 20 of 28 genuine attempts (71%) were **applied on the site**
- 8 were genuinely not applied
- the 9 navigation errors stayed unapplied, as expected

So the submit path works. The failure was in **confirmation**, not submission.

### 3. Root cause

`_confirm_naukri_apply` ended with `page.reload()`. After a chatbot, the SPA is
not on the job's own URL, so reloading re-rendered the chatbot/recommendations
page and could never show `.already-applied`. The offline reconciler works
because it does a fresh `page.goto(job.url)`.

### 4. Fix

`jobs_auto_apply/naukri/apply.py`: added `_confirm_applied_on_fresh_detail`,
called before declaring failure. It navigates to the job's own detail URL (same
`goto_naukri_job_detail` used by the apply path) and checks
`.already-applied`, twice with 2.5 s / 4 s waits.

## Verification

`scripts/verify_naukri.py --keywords "react developer" --scan 30 --max-jobs 2`

```
Naukri apply confirmed (fresh detail load): Java React Developer
Applied on Naukri: Java React Developer

reported applied this run : 1
history entries recorded  : 11  (applied 1, abandoned 10)
confirm failures in log   : 0

RESULT: submit path confirmed. Safe to restore Naukri SRPs.
```

The new key `naukri:200926014684` was absent from the pre-run backup, so it is a
real new application, not a re-detection of an old one.

## What is still true (and is not a submit bug)

Of 20 quick-apply listings on one SRP, 8 were rejected at the detail page as
`non-quick-apply (early)`, 1 for salary, 1 needed an unanswered question. That
is a **supply** problem, and it matches the report's 34/70 detail-page loss.
The `--scan` flag now lets a verification walk 30 listings while capping
confirmed submits at `--max-jobs`.

## Files

- `jobs_auto_apply/naukri/apply.py` — fresh-detail confirmation
- `scripts/verify_naukri.py` — controlled verification, `--scan`
- `scripts/reconcile_naukri_applied.py` — added `--limit`
