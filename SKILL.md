---
name: job_auto_apply
description: Apply to a target number of jobs across LinkedIn Easy Apply and Indeed Quick Apply for a given user, then report a one-line summary back to the user.
metadata:
  openclaw:
    os: ["darwin"]
    requires:
      bins: ["python3"]
---

# Job Auto-Apply

You apply to jobs for one user via LinkedIn Easy Apply and Indeed Quick Apply, using the `browser` tool. Per-user state lives under `<SKILL_DIR>/data/<user_id>/` and `<SKILL_DIR>/sessions/<user_id>/`.

`<SKILL_DIR>` is this skill's installed folder. Resolve it at runtime; every `state.py` call carries `--user_id`.

## State helper

```
python3 <SKILL_DIR>/state.py {has_profile|read|append|set_cred} --user_id <id> [...]
```

Files: `profile.json` (PII + eligibility + skill_years + default_years), `credentials.json` (0600), `memory.json` (`{"answers": {sha→answer}}`), `job_log.csv`, `sessions/<user_id>/{linkedin,indeed}.json`.

## Inputs to collect from the user

`user_id`, `resume_path` (absolute PDF path), `job_titles` (list), `target_count` (int > 0). Optional: `headless` (default true).

If titles are a single string, split on commas / and / & and confirm the parsed list back in one sentence before starting.

## Architecture — one subagent per single application

**The parent dispatcher spawns one subagent per single application, not one subagent for the whole batch.** Each subagent runs Steps 0–4 below for exactly one job, reports `applied | skipped:<reason>`, then exits. The parent keeps the running counter and respawns until `target_count` is reached or both platforms are capped.

This bounds each subagent's working context to a single posting and lets each one start with a fresh prompt cache. **Do not loop multiple applications inside one subagent** — that is what blew up prior runs.

The parent may run LinkedIn and Indeed subagents concurrently, but each individual subagent applies to exactly one job. Default concurrency cap: **at most 2 in-flight subagents at any time** (one per platform). Higher concurrency does not help — per-platform pacing dominates wall time and risks anti-automation flags.

## Step 0 — Preload (once per subagent)

1. `state.py has_profile`. If false, follow `references/onboarding.md`, then continue.
2. Read `job_log.csv` once → in-memory dedup index.
3. Read `memory.json` once → in-memory answer cache.
4. Parse the resume PDF text once and keep it in working memory.

## Step 1 — Login (once per subagent, per platform)

Open the platform with stored session state from `sessions/<user_id>/<platform>.json`. If you see signed-in chrome, continue. Otherwise read credentials and submit the login form. On a 2FA / email-PIN challenge, ask the user once, wait, type it in. After two failed attempts, stop and reply: `Could not log in to <platform> for <user_id>. Please re-run bootstrap to update credentials.`

Save session state on success.

## Step 2 — Find one candidate

Sort by most recent (LinkedIn `&sortBy=DD&f_AL=true`, Indeed `&sort=date`). Load the search page, scroll once for ~25 cards, extract from cards in **one DOM pass**: canonical URL (strip tracking — keep `currentJobId` for LinkedIn, `jk` for Indeed), company, role, posted-time, badge presence.

**Pre-screen in the list:** if the card lacks "Easy Apply" (LinkedIn) or "Apply with Indeed" (Indeed), the job redirects to an external ATS. Log `skipped:external_ats` (URL in `notes`) and try the next card. Do not open the posting.

Title match is loose: any job the platform surfaces is a valid candidate. Filtering happens at dedup and form-fill time.

## Step 3 — Dedup

Skip if **either**:
- the canonical URL is in the dedup index with status `applied`, OR
- a `(company, role)` pair is in the index with status `applied` and you judge them the same opportunity. Strip Sr/Senior/Staff/Lead. Treat aliases as one (Alphabet ≡ Google ≡ Google LLC; Meta ≡ Facebook; Data Engineer ≡ Big Data Engineer ≡ Data Platform Engineer at the same company).

On dedup: log `skipped:duplicate` (matched URL in `notes`) and try the next card. Do not open the posting, do not pause.

## Step 4 — Apply to the chosen job

Click Apply. For each form step:

1. Upload the resume from `resume_path` into any resume-shaped file input.
2. Read every visible field in one DOM scan and batch-fill per `references/form_question_rules.md`.
3. Click Next/Continue/Review.

**Scope every DOM read.** Never request the full page. In order of preference: `[role="dialog"] form`, then the nearest `<form>` element to the Apply button, then a labelled `<section>`. The job feed, sidebar, recommendations, and ads outside the dialog are noise — do not read them into context.

**After clicking Next, the previous step's DOM is no longer relevant.** Do not re-read it, do not reference it. Treat each step as a fresh page. This keeps the subagent's working context bounded.

Continue until you reach Submit. Click Submit, wait for the confirmation state (banner / toast / "Application sent" / new modal).

If you encounter:
- a CAPTCHA → log `skipped:captcha`, dismiss the modal, exit subagent.
- "not eligible" / role unavailable → log `skipped:not_eligible`, exit subagent.
- an unrecognised state after 15 step iterations → log `skipped:unknown_state`, exit subagent.

On submission confirmation:

```
state.py append --user_id X --kind log --row '{"platform":"linkedin","url":"...","company":"...","role":"...","status":"applied"}'
```

Then emit one final assistant message in this exact form and stop — no further tool calls:

```
Applied: <company>/<role>. Discarding form DOM.
```

The parent dispatcher reads that line, handles pacing, and respawns for the next job. If you skipped (CAPTCHA / not_eligible / unknown_state / needs_factual / external_ats / duplicate), the final message is `Skipped:<reason>: <company>/<role>` instead — same rule, no further tool calls.

For form-question rules see `references/form_question_rules.md`. For hard rules see `references/safety.md`.

## Pacing (per-context, do not lower)

| Action | Wait |
|---|---|
| Between page actions inside a context | 4–10 s |
| Between successful submissions inside a context | 30–90 s |

Concurrent contexts must each respect these — concurrency is not a license to speed up.

## Safety caps

- 25 successful applications per platform per user per day.
- If a platform raises a session/CAPTCHA error, that loop stops; the other keeps going.

## Termination + summary (parent dispatcher)

Stop when any is true: `applied == target_count`, all queues exhausted, or both platforms capped.

Send exactly one chat message:

```
Batch Complete for <user_id>. Total Applied: <X>. Platforms: LinkedIn (<Y>), Indeed (<Z>). Log: <log_path>
```

`<log_path>` and counts come from `state.py read --user_id <user_id> --kind status`. If skips of one kind exceed 5 (e.g. many `skipped:captcha`), append one short sentence. Otherwise the single line is the entire reply.

## Status check (no apply)

If the user asks "how am I doing?" / "status of <user_id>?", run `state.py read --user_id <user_id> --kind status` and reply in one line: applied count, per-platform breakdown, sessions valid?, profile present?
