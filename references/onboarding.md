# Onboarding (run only when `state.py has_profile` returns false)

Ask the user the questions below in chat, **one or two at a time**, to keep the conversation natural. Save batched answers to `profile.json` as you go (read current profile, merge, write back). Capture credentials with `state.py set_cred` (it enforces 0600 on disk).

## Identity (save to `profile.json`)

`first_name`, `last_name`, `phone` (with country code), `address`, `city`, `state`, `zip`, `country`, `linkedin_url`, `github_url` (or empty), `portfolio_url` (or empty)

## Eligibility (always ask; stable)

- `work_authorization` — Yes/No
- `sponsorship_now` — Yes/No
- `sponsorship_future` — Yes/No
- `willing_relocate` — Yes/No
- `work_mode` — Remote / Hybrid / Onsite / Any

## Compensation / timing

- `salary_expectation` — number or short range
- `notice_period` — short text (default "Two weeks" if user defers)

## Experience baseline

- `default_years` — integer years overall
- `skill_years` — JSON object skill→years, e.g. `{"python":7,"sql":6,"airflow":4}`. Ask for top 5–10 skills the user wants to emphasise.

## EEO / demographic (default to "Decline to answer" unless user overrides)

- `veteran_status`, `disability_status`, `gender`, `race_ethnicity`

## Credentials (per platform)

```
state.py set_cred --user_id X --platform linkedin --email E --password P
state.py set_cred --user_id X --platform indeed   --email E --password P
```

When done, confirm in one short message ("Saved your profile. Ready when you are."), then continue with the apply flow.
