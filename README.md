# openclaw_apply

OpenClaw skill that auto-applies to jobs on LinkedIn Easy Apply + Indeed Quick Apply on behalf of a user, triggered through whatever chat front-end OpenClaw is wired to (QQ, Telegram, Slack, etc.).

## Files

```
SKILL.md          # The whole application: instructions to the OpenClaw agent.
state.py          # Tiny stdin-free JSON/CSV helper invoked via `exec`. No business logic.
data/<user>/      # Per-user state (profile, memory, log, credentials)
sessions/<user>/  # browser-tool storage state per platform
```

## How it works

The OpenClaw agent reads `SKILL.md` and acts on it directly. It uses:

- the **`browser`** tool to drive LinkedIn / Indeed,
- the **`exec`** tool to call `python3 state.py …` for state IO,
- the **OpenClaw chat front-end** (QQ / Telegram / Slack / etc.) to talk to the user — ask, confirm, deliver the final summary.

Almost no Python logic is needed because the LLM does the classification, the
form filling, the dedup judgment, and the essay writing in-context. `state.py`
exists only because file IO needs to be atomic, schema-stable, and `chmod 0600`
for credentials.

## Setup

Clone or copy this folder into your OpenClaw skills directory (typically `~/.openclaw/workspace/skills/job_auto_apply/`), then:

```bash
cd /path/to/job_auto_apply
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # currently nothing — stdlib only
# (No Playwright install here — the OpenClaw `browser` tool handles browsers.)
```

Register the skill with OpenClaw per the docs at https://docs.openclaw.ai/tools/creating-skills (point it at this folder's `SKILL.md`).

## Onboarding a new user

When the user first asks the skill to apply, the agent detects there's no
`profile.json` and walks them through the bootstrap questions in chat. There is
no separate command to run.

## Running a batch

The user simply messages the chat front-end, e.g.: *"Apply to 20 data engineer
or big data engineer jobs for alice, resume at /path/to/resume.pdf"*.

The agent confirms the parsed inputs, runs the loop, and posts back:

```
Batch Complete for alice. Total Applied: 20. Platforms: LinkedIn (12), Indeed (8). Log: <absolute_path_to>/data/alice/job_log.csv
```

## state.py reference

```
state.py read    --user_id X --kind {profile|memory|credentials|log|status}
state.py write   --user_id X --kind {profile|memory} --json '{...}'
state.py append  --user_id X --kind log --row '{...}'
state.py set_cred --user_id X --platform {linkedin|indeed} --email E --password P
state.py has_profile --user_id X
```

All commands print JSON to stdout for the agent to parse.

## Trade-offs (acknowledged)

- Credentials are stored as plaintext JSON, `chmod 0600`. Protect the host machine — anyone with read access to your home directory can read them.
- LinkedIn / Indeed ToS forbid automation. Pacing in SKILL.md (4–10s between actions, 30–90s between submissions, 25/day cap) reduces but does not eliminate suspension risk.
- v1 only handles Easy Apply / Quick Apply — jobs that redirect off-platform are skipped and logged.
