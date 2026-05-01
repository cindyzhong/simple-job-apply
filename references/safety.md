# Things you must not do

- Do not lower the per-context pacing (4–10 s between actions, 30–90 s between submissions) just because two contexts are running concurrently — that defeats the anti-detection purpose.
- Do not bypass the dedup check ever.
- Do not retry a failed login more than twice without asking the user for help.
- Do not invent factual data (addresses, phone numbers, work history) — always read from `profile.json` or ask.
- Do not lie on Class B questions. If the user needs sponsorship and the JD says "must not require sponsorship", log `skipped:not_eligible` and move on.
- Do not write essays longer than 200 words — recruiters skim.
- Do not store credentials anywhere except via `state.py set_cred`.
