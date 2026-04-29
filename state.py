"""Tiny state helper for the job_auto_apply skill.

The OpenClaw agent invokes this via the `exec` tool. All real logic
(searching, form-filling, classifying, dedup judgment) lives in SKILL.md
and is performed by the LLM. This script only handles atomic JSON/CSV IO,
file permissions for credentials, and printing well-formed JSON to stdout
so the agent can parse it.

Subcommands:
  read    --user_id X --kind {profile|memory|credentials|log|status}
  write   --user_id X --kind {profile|memory}        --json '{...}'
  append  --user_id X --kind log                     --row  '{...}'
  set_cred  --user_id X --platform {linkedin|indeed} --email E --password P
  has_profile  --user_id X
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SESSIONS = ROOT / "sessions"


def _user_dir(user_id: str) -> Path:
    p = DATA / user_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _session_dir(user_id: str) -> Path:
    p = SESSIONS / user_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def _write_json(path: Path, data: Any, mode: int | None = None) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)
    if mode is not None:
        os.chmod(path, mode)


def _read_log_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _ensure_log(path: Path) -> None:
    if not path.exists():
        with path.open("w", newline="") as f:
            csv.writer(f).writerow(
                ["ts", "platform", "url", "company", "role", "status", "notes"]
            )


def cmd_read(args: argparse.Namespace) -> int:
    ud = _user_dir(args.user_id)
    if args.kind == "profile":
        out = _read_json(ud / "profile.json", {})
    elif args.kind == "memory":
        out = _read_json(ud / "memory.json", {"answers": {}})
    elif args.kind == "credentials":
        out = _read_json(ud / "credentials.json", {})
    elif args.kind == "log":
        out = _read_log_rows(ud / "job_log.csv")
    elif args.kind == "status":
        rows = _read_log_rows(ud / "job_log.csv")
        applied = sum(1 for r in rows if r.get("status") == "applied")
        per: dict[str, int] = {}
        for r in rows:
            if r.get("status") == "applied":
                per[r["platform"]] = per.get(r["platform"], 0) + 1
        sd = _session_dir(args.user_id)
        out = {
            "user_id": args.user_id,
            "profile_exists": (ud / "profile.json").exists(),
            "credentials_exists": (ud / "credentials.json").exists(),
            "applied_total": applied,
            "applied_per_platform": per,
            "log_path": str(ud / "job_log.csv"),
            "sessions": {
                "linkedin": (sd / "linkedin.json").exists(),
                "indeed": (sd / "indeed.json").exists(),
            },
        }
    else:
        print(f"unknown kind: {args.kind}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    ud = _user_dir(args.user_id)
    data = json.loads(args.json)
    if args.kind == "profile":
        _write_json(ud / "profile.json", data)
    elif args.kind == "memory":
        _write_json(ud / "memory.json", data)
    else:
        print(f"write does not support kind={args.kind}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "kind": args.kind}))
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    if args.kind != "log":
        print("append only supports kind=log", file=sys.stderr)
        return 2
    ud = _user_dir(args.user_id)
    path = ud / "job_log.csv"
    _ensure_log(path)
    row = json.loads(args.row)
    with path.open("a", newline="") as f:
        csv.writer(f).writerow(
            [
                row.get("ts") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                row.get("platform", ""),
                row.get("url", ""),
                row.get("company", ""),
                row.get("role", ""),
                row.get("status", ""),
                row.get("notes", ""),
            ]
        )
    print(json.dumps({"ok": True, "path": str(path)}))
    return 0


def cmd_set_cred(args: argparse.Namespace) -> int:
    ud = _user_dir(args.user_id)
    path = ud / "credentials.json"
    creds = _read_json(path, {})
    creds[args.platform] = {"email": args.email, "password": args.password}
    _write_json(path, creds, mode=0o600)
    print(json.dumps({"ok": True, "platform": args.platform}))
    return 0


def cmd_has_profile(args: argparse.Namespace) -> int:
    p = _user_dir(args.user_id) / "profile.json"
    print(json.dumps({"exists": p.exists()}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_read = sub.add_parser("read")
    p_read.add_argument("--user_id", required=True)
    p_read.add_argument("--kind", required=True,
                        choices=["profile", "memory", "credentials", "log", "status"])
    p_read.set_defaults(fn=cmd_read)

    p_write = sub.add_parser("write")
    p_write.add_argument("--user_id", required=True)
    p_write.add_argument("--kind", required=True, choices=["profile", "memory"])
    p_write.add_argument("--json", required=True)
    p_write.set_defaults(fn=cmd_write)

    p_app = sub.add_parser("append")
    p_app.add_argument("--user_id", required=True)
    p_app.add_argument("--kind", required=True, choices=["log"])
    p_app.add_argument("--row", required=True)
    p_app.set_defaults(fn=cmd_append)

    p_cred = sub.add_parser("set_cred")
    p_cred.add_argument("--user_id", required=True)
    p_cred.add_argument("--platform", required=True, choices=["linkedin", "indeed"])
    p_cred.add_argument("--email", required=True)
    p_cred.add_argument("--password", required=True)
    p_cred.set_defaults(fn=cmd_set_cred)

    p_has = sub.add_parser("has_profile")
    p_has.add_argument("--user_id", required=True)
    p_has.set_defaults(fn=cmd_has_profile)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
