# Form Question Rules

Read this only when filling an apply form's questions. The skill's main loop tells you when.

## Per-step batch fill

For each modal step, do this once — not field-by-field:

1. Read every visible field in one DOM scan into a JSON array:
   ```
   [{"field_id": "...", "label": "What is your phone number?", "type": "tel", "options": null, "required": true}, ...]
   ```
   Use whatever stable identifier the platform exposes (`name`, `aria-labelledby`, or a synthesised index) as `field_id`.
2. For each field, compute `sha1(lowercase(collapse_ws(label)))` and look it up in the in-memory `memory.json["answers"]` dict. Pre-fill cache hits.
3. For the remaining fields, issue **one** LLM call with: the unanswered field array, `profile.json`, the JD text, the resume text, the company + role, and the four-class rules below. Ask for a JSON array `[{"field_id": "...", "answer": "..."}]`. Use the literal `null` for any required factual field you cannot resolve.
4. Apply each answer. If any required answer is `null`, ask the user about that field, log `skipped:needs_factual`, and abandon this job.
5. Write newly-resolved answers back to `memory.json` in **one** write at the end of the step.

## Four classes

### Class A — factual (PII, contact, location)
Full name, email, phone, address, city, ZIP, country, LinkedIn URL.

1. Use the matching `profile.json` field.
2. If genuinely missing, ask the user once, save to `profile.json`, continue.
3. If the user does not reply within ~2 minutes and the field is required, log `skipped:needs_factual` and move on.

### Class B — eligibility (sponsorship, work auth, relocate, EEO, work mode, citizenship)

1. Read `profile.json`. Bootstrap captured every standard eligibility field — use those.
2. For a novel eligibility question, ask the user once, save under a sensibly-named key in `profile.json`, never re-ask.

### Class C — skill_years
"How many years of X?"

- If `skill_years[<skill>]` is in `profile.json`, that is the user's actual.
- Parse the JD for an "N+ years" / "N-M years" / "minimum N years" requirement for that skill. Take `max(requirement, user_actual)`. Fall back to `default_years` if the user has no entry.
- **Never enter a number below the JD's requirement** — under-claiming wastes the application.
- Clamp to a believable max if the JD demands >30 years.

### Class D — open_ended (essays, "why this company", "tell us about a project")

- 90–160 words, first person, professional. Reference one or two specific things from the JD or the company. No clichés ("passionate", "rockstar"), no filler.
- Inputs: company name, role, JD, resume text.
- Cache in `memory.json` under `(company_lower, role_lower, question_hash)` so the same opportunity does not re-generate.

## Caching rules

- Class A: cache forever in `profile.json`.
- Class B: cache forever in `profile.json`.
- Class C: cache per-skill in `profile.json` **only if the user told you** the number; JD-derived computations are not cached.
- Class D: cache in `memory.json` under `(company_lower, role_lower, question_hash)`.
- Class A/B answers also cache in `memory.json` under `question_hash` so any future form with the same wording resolves instantly.
