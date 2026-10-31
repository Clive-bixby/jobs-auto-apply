# Role gate: separator-insensitive matching + role families

**Date:** 2026-10-29
**Status:** approved (option A of three laid out in conversation)

## Intent

The role gate is the only filter that runs on every platform, and it rejects
~18% of otherwise-eligible listings because of spelling, not because the role is
wrong. Run 8 (`data/run-20261026h.log`) logged 456 role-skip events / 389
distinct titles. Of those:

- 81 events (18%) were target-role variants — 36 AI/ML, 45 spelling variants
- 130 off-target, 116 seniority, 72 no-experience stack, 16 intern, 41 other

The report's claim that "456 skips are mostly naming variants" is wrong, but the
81 are real, they are the user's own target roles, and they are recoverable
without loosening the gate's intent.

## Goals

- One config entry matches every separator spelling of a role:
  `Full Stack` = `Full-Stack` = `FullStack` = `Full  Stack`.
- `Node.js Developer` also matches `Node JS Developer` and `Nodejs Developer`.
- Add the missing role *families* (MERN/MEAN, SDE, AI/ML set) as single entries.
- Preserve every existing skip rule: seniority, intern, no-experience stacks.

## Non-goals

- Per-platform preference blocks. Evidence says they would not pay for
  themselves (see conversation).
- Changing the salary floor, `include_no_salary`, feeds, or submit paths.
- Changing `skip_no_experience_skills` behaviour (`JavaScript` must never be
  treated as `Java`).

## Anti-goals

- Matching short keywords as substrings (`SDE` must not match `SDET`, `AI` must
  not match `email`).
- Admitting roles the candidate cannot do (C++, .NET, Java-only, QA, data).

## Constraints

- Matching stays config-driven; no hard-coded keyword list in code.
- `should_skip_role` keeps its signature and reason strings.
- `skip_role_patterns` (raw regex) are unchanged.
- Existing tests keep passing.

## Approaches considered

| # | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | Flexible separators inside `_keyword_regex` + add role families to config | ~15 lines of code, no new config surface, fixes all portals at once | **picked** |
| B | Tokenise titles and keywords, match token subsequences | Handles camelCase cleanly but needs special cases for `iOS`, `DevOps`, `WordPress` and risks `JavaScript` → `Java` | rejected |
| C | Enumerate every spelling in `require_role_keywords` | No code change, but ~60 list entries that drift | rejected |

A is chosen because the failures are all separator/camel-boundary failures, and a
single regex change fixes them without weakening word boundaries.

## The how

1. `_keyword_regex` splits the keyword into alphanumeric words and joins them
   with `[\s\-_./]*` (zero-width allowed), keeping `\b` at both ends.
   - `Full Stack` → `\bfull[\s\-_./]*stack\b` → matches `FullStack`.
   - `Node.js Developer` → `\bnode[\s\-_./]*js[\s\-_./]*developer\b` → matches
     `Node Js Developer`, `Nodejs Developer`.
   - Single words are unchanged: `\bjava\b` still does not match `JavaScript`.
2. `config.yaml` / `config.example.yaml`: replace the spelling-permutation list
   with role families (Full Stack, Front End, Back End, Software Engineer, SDE,
   MERN, MEAN, React/Node/Python, AI/ML set). Comment says "families, not
   spellings".
3. Tests in `tests/test_preferences.py` cover: separator variants, Node/MERN
   spellings, AI family, `SDE` vs `SDET`, and `JavaScript` vs `Java`.

## Left to the builder

- Exact AI/ML family membership. Chosen set matches the user's stated
  `core_skills` (LLMs, RAG, vector search): AI Engineer, AI Developer, AI/ML,
  ML Engineer, Machine Learning Engineer, GenAI Engineer, Generative AI Engineer,
  LLM Engineer, MLOps Engineer, Prompt Engineer, Agentic AI, Artificial
  Intelligence Engineer. Computer Vision / AI Researcher deliberately excluded.
- Whether to add `Forward Deployed Engineer` later (left out: usually mid-level).
