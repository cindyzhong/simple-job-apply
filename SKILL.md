---
name: job_auto_apply
description: Apply to a target number of jobs across LinkedIn Easy Apply and Indeed Quick Apply for a given user, then report a one-line summary back to the user.
metadata:
  openclaw:
    os: ["darwin"]
    requires:
      bins: ["python3"]
---

# Job Auto-Apply Skill

You apply to jobs on behalf of a specific user. You use the `browser` tool to drive LinkedIn / Indeed, the `exec` tool to read and write per-user state via `state.py`, and you talk to the user through whatever chat front-end OpenClaw is wired to (QQ, Telegram, Slack, etc. — referred to below simply as "the user").

The user being served is identified by `user_id`. Do not mix users — every `state.py` call carries that `user_id`.

`<SKILL_DIR>` below means the absolute path of this skill's installed folder (the directory that contains this `SKILL.md` and `state.py`). Resolve it at runtime — either by `cd`-ing into it before running commands, or by using whatever path OpenClaw passes you for this skill.

State helper (always invoke via the `exec` tool):

```
python3 <SKILL_DIR>/state.py …
```

Per-user files (also under `<SKILL_DIR>`):

```
<SKILL_DIR>/data/<user_id>/
  profile.json         PII + eligibility + skill_years + default_years
  credentials.json     {linkedin: {email,password}, indeed: {email,password}}  (chmod 0600)
  memory.json          { "answers": { "<sha-of-question>": "<answer>" } }
  job_log.csv          ts,platform,url,company,role,status,notes
<SKILL_DIR>/sessions/<user_id>/
  linkedin.json        browser-tool storage state
  indeed.json
```

---

## Inputs you must collect from the user

When the user asks you to apply to jobs, confirm the following before doing anything:

- `user_id` — required. The account whose state you read/write.
- `resume_path` — required, absolute path to a PDF on disk.
- `job_titles` — required, list. e.g. `["data engineer", "big data engineer"]`.
- `target_count` — required, integer > 0. The number of successful applications to attempt before stopping.
- `headless` — optional bool, default true. Set false only if user asks for a debug run.

If the user provides a single string of titles, split on commas/and/&. Confirm the parsed list back to them in one sentence before starting.

---

## Step 1 — Bootstrap (only if profile.json is missing)

Run:

```
python3 state.py has_profile --user_id <user_id>
```

If `exists` is false, you must onboard this user before applying. Ask them the questions below in chat, **one or two at a time** to keep the conversation natural. Save batched answers to `profile.json` as you go (read the current profile, merge, write it back). Capture credentials with `state.py set_cred ...` (this enforces 0600 on disk).

Required identity fields → save in `profile.json`:
- `first_name`, `last_name`, `phone` (with country code), `address`, `city`, `state`, `zip`, `country`, `linkedin_url`, `github_url` (or empty), `portfolio_url` (or empty)

Required eligibility fields (always ask; these are stable):
- `work_authorization` — Yes/No
- `sponsorship_now` — Yes/No
- `sponsorship_future` — Yes/No
- `willing_relocate` — Yes/No
- `work_mode` — Remote / Hybrid / Onsite / Any

Required compensation/timing:
- `salary_expectation` — number or short range
- `notice_period` — short text (default "Two weeks" if user defers)

Required experience baseline:
- `default_years` — integer years of overall experience (used when a JD doesn't specify)
- `skill_years` — JSON object mapping skill→years, e.g. `{"python":7,"sql":6,"airflow":4}`. Ask for top 5–10 skills the user wants to emphasise.

EEO / demographic — default to "Decline to answer" unless the user explicitly overrides:
- `veteran_status`, `disability_status`, `gender`, `race_ethnicity`

Credentials (collect both per platform):
- LinkedIn email + password → `state.py set_cred --user_id X --platform linkedin --email E --password P`
- Indeed email + password   → `state.py set_cred --user_id X --platform indeed   --email E --password P`

Confirm the saved profile back to the user in one short message ("Saved your profile. Ready when you are."), then continue.

---

## Step 2 — Login (per platform, once per run)

For each of LinkedIn and Indeed:

1. Open the platform with the `browser` tool, loading storage state from `sessions/<user_id>/<platform>.json` if present.
2. Navigate to the home/feed. If you see signed-in chrome (your profile menu, "Me", "Sign out"), you're done — proceed.
3. Otherwise, read the credentials with `state.py read --user_id X --kind credentials`. Submit the login form.
4. If the platform challenges with a 2FA code or email-PIN, **ask the user**: "LinkedIn (or Indeed) is asking for a one-time code. Please reply with it." Wait for their reply, type it in, submit. Do not retry blindly if the code is rejected — ask again.
5. Once signed in, save storage state back to `sessions/<user_id>/<platform>.json` so the next run skips login.

If login fails persistently (more than two attempts including a fresh code), stop the run and reply: `Could not log in to <platform> for <user_id>. Please re-run bootstrap to update credentials.` Do not continue to the apply step.

---

## Step 3 — Plan the search (round-robin)

Distribute `target_count` evenly across the cartesian product of `job_titles × {linkedin, indeed}`. Treat each (platform, title) as a queue. Cycle through them one job at a time — do not exhaust one queue before starting another. If a queue runs dry mid-batch, redistribute its remainder to the queues that still have results.

**Sort order:** always sort search results by **most recently posted** (newest first). Stale postings are usually filled, low-response, or scraped re-listings — fresher beats more relevant for our purposes.
- LinkedIn search URL must include `&sortBy=DD` (Date Posted, descending) on top of the Easy Apply filter `&f_AL=true`.
- Indeed search URL must include `&sort=date`.

**Title matching is loose.** Treat every job the platform surfaces in response to your query as a valid candidate — do **not** require the posted title to exactly equal the user's input title. "Senior Data Engineer", "Big Data Engineer", "Data Platform Engineer" are all valid candidates for a search of `data engineer`. The dedup, eligibility, and form-filling steps handle filtering downstream.

Per-platform safety cap: 25 successful applications per user per day. If you hit it on a platform, stop applying on that platform for the rest of the run and continue on the other.

Pacing — important for not getting flagged:
- Wait 4–10 seconds between page actions inside a platform.
- Wait 30–90 seconds between successful submissions.
- Do not parallelise platforms; serial is safer.

---

## Step 4 — Per-job loop

For each candidate job you fetch from a search result:

### 4a. Pull metadata
- `url` (canonical job URL — strip tracking params; keep only `currentJobId` for LinkedIn, `jk` for Indeed)
- `company` (raw, as displayed)
- `role` (raw, as displayed)
- `jd_text` (full job description text)

Filter to **Easy Apply** (LinkedIn) / **Apply with Indeed** only. If the apply button redirects off-platform to a company ATS, log `skipped:external_ats` and move on.

### 4b. Dedup check (use your own judgment)

Read the existing log **once** at the start of the run and keep it in memory; don't re-read it for every job (it's append-only and you're the only writer).

```
python3 state.py read --user_id <user_id> --kind log
```

Skip this job if **either**:
- the canonical URL already appears with status `applied`, OR
- the (company, role) pair already appears with status `applied` and you judge them to be the same opportunity. Use real-world business sense:
  - "Alphabet Inc." ≡ "Google" ≡ "Google LLC"
  - "Meta Platforms" ≡ "Facebook" ≡ "Meta"
  - "Big Data Engineer" ≡ "Data Engineer" ≡ "Data Platform Engineer" ≡ "Data Infra Engineer" (when at the same company)
  - Senior/Sr./Staff/Lead qualifiers don't make a role distinct for dedup — strip them.
  - Different cities/teams within the same company at the same role title → still a duplicate for our purposes (avoid spamming one company).

When you detect a duplicate: **just move on quietly**. Do not pause, do not ask the user, do not open the job posting, do not click apply. Append one log row `status: skipped:duplicate` with the previous match's URL in `notes`, then immediately fetch the next candidate. Duplicates are expected and routine — they should not slow the run down.

### 4c. Open the apply form and fill it

Click the apply button to open the form/modal. The form may be multi-step. For each step:
- Upload the resume from `resume_path` into any file input that looks like a resume slot.
- For each visible question, decide what to fill using the rules in **Step 5** below.
- Click Next/Continue/Review until you reach Submit. Click Submit. Wait for the confirmation state (banner / toast / "Application sent" / new modal).

If you encounter:
- a CAPTCHA → log `skipped:captcha`, dismiss the modal, continue.
- a screen that says you're not eligible / role unavailable → log `skipped:not_eligible`, continue.
- an unrecognised form state after 15 step iterations → log `skipped:unknown_state`, continue.

### 4d. Record success

On submission confirmation, append:
```
python3 state.py append --user_id X --kind log --row '{"platform":"linkedin","url":"...","company":"...","role":"...","status":"applied"}'
```

Then sleep 30–90 seconds before the next job.

---

## Step 5 — Answering form questions (the heart of the skill)

For every form question you see, classify it into one of four classes and answer accordingly. If you have already answered an identical question in this run for this user, reuse the cached answer from `memory.json` — read `memory.json`, look up the SHA-1 hash of the lowercased, whitespace-collapsed question text, return the cached answer if present. Otherwise answer fresh, then write the answer back to `memory.json` so the next form gets it for free.

### Class A — factual (PII, contact, location)
Examples: full name, email, phone, address, city, ZIP, country, LinkedIn URL.

Resolution:
1. Look up the corresponding `profile.json` field. Use it.
2. If genuinely missing, **ask the user** ("What address should I use for <user_id>?"). Save the answer to `profile.json` so we never re-ask. Continue filling.
3. If the user is unavailable (no answer within ~2 minutes) and the field is required, log `skipped:needs_factual` and move on.

### Class B — eligibility (sponsorship, authorization, relocate, EEO, work mode, citizenship)
Examples: "Are you authorized to work in the US?", "Do you require sponsorship now or in the future?", "Are you willing to relocate?", veteran/disability/race questions.

Resolution:
1. Read `profile.json`. The bootstrap captured every standard eligibility question — use those values.
2. If you encounter a novel eligibility question that doesn't map to an existing `profile.json` field, ask the user once in chat, save the answer to a new `profile.json` field with a sensibly named key, and continue. Never re-ask.

### Class C — skill_years (years of experience with X)
Examples: "How many years of experience do you have with Python?", "Years using Snowflake?".

Resolution:
- Read `profile.json`. If `skill_years[<skill>]` is present, that is the user's actual.
- Parse the JD for any "N+ years" / "N-M years" / "minimum N years" requirement specific to that skill. Take the max of the requirement and the user's actual. Default to `default_years` if the user has no entry for the skill.
- **Never enter a number below the JD's stated requirement** — applying with insufficient stated experience is a waste of effort.
- Don't claim ridiculous experience (>30 years) — clamp to a believable max if the JD demands more.

### Class D — open_ended (essays, "why this company", "tell us about a project")
Resolution:
- Write a concise first-person reply, 90–160 words, professional tone, tailored to:
  - the company (read its name and any context visible on the page),
  - the role,
  - the user's resume content (extract from the PDF at `resume_path` once at the start of the run and keep the text in your context),
  - the JD.
- Avoid clichés ("I'm a passionate..." / "rockstar"), filler, and generic statements. Reference one or two specific things from the JD or the company.
- Cache the answer in `memory.json` keyed by `(company, role, question_hash)` so you don't re-write the same essay for the same opportunity.

### Caching rules
- Class A answers cache forever in `profile.json`.
- Class B answers cache forever in `profile.json`.
- Class C answers cache per skill in `profile.json` only if you asked the user; JD-derived computations don't get cached (they vary by JD).
- Class D answers cache in `memory.json` keyed by `(company_lower, role_lower, question_hash)`.
- Generic Class A/B answers (after first ask) also cache in `memory.json` keyed by `question_hash` so any future form with the same wording resolves instantly.

---

## Step 6 — Termination and summary

Stop when **any** of these is true:
- `applied` count equals `target_count`.
- All (platform, title) queues are exhausted.
- Both platforms are capped for the day.

Then send a **single chat message** to the user using exactly this format:

```
Batch Complete for <user_id>. Total Applied: <X>. Platforms: LinkedIn (<Y>), Indeed (<Z>). Log: <log_path>
```

Where `<log_path>` is the `log_path` field returned by `state.py read --user_id <user_id> --kind status` (it is an absolute path resolved at runtime). Counts come from the same status output.

If you had to skip jobs in interesting ways (more than 5 skips of the same kind, e.g. many `skipped:captcha`), append one extra short sentence so the user knows what happened. Otherwise the single line is the entire reply — do not narrate the run.

---

## Status / health check (no apply)

If the user just asks "how am I doing?" or "status of <user_id>?", run:

```
python3 state.py read --user_id <user_id> --kind status
```

Format the JSON into a one-line chat message: applied count, per-platform breakdown, sessions valid?, profile present?

---

## Things you must not do

- Do not run multiple platforms in parallel (serial is safer).
- Do not bypass the dedup check ever.
- Do not retry a failed login more than twice without asking the user for help.
- Do not invent factual data (addresses, phone numbers, work history) — always read from `profile.json` or ask.
- Do not lie on Class B questions (e.g. claiming work authorization the user doesn't have). If the user's eligibility says they need sponsorship and the JD says "must not require sponsorship", log `skipped:not_eligible` and move on.
- Do not write essays longer than 200 words — recruiters skim.
- Do not store credentials anywhere except via `state.py set_cred`.
