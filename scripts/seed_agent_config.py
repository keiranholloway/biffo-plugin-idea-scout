#!/usr/bin/env python3
"""Seed the admin-editable prompt/model config for Idea Scout's four agents.

Unlike the build types and the fan-in workflow, this one is **not** a hard
prerequisite: ``IdeaScoutService._resolve_agent`` falls back to the built-in
prompt in ``idea_scout.definitions`` when a role has no configured row, so the
plugin works without it. Seeding exists so an admin has something to edit in the
UI rather than an empty page, and so the live config starts identical to what
the code would have run.

Note the synthesis prompt is seeded here **and** carried in the fan-in workflow
definition (``seed_fan_in_workflow.py``), because the engine — not this plugin —
is what fires the synthesis agent, and the engine reads its instructions from the
workflow's ``action_config``. Editing this row alone therefore changes nothing
for synthesis; the workflow is the live copy. That is a wart of moving the
sequencing into the engine, and worth knowing before wondering why an edit had
no effect.

Usage:
    CORE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com \
    ADMIN_BEARER_TOKEN=<a real Cognito admin id/access token> \
    python scripts/seed_agent_config.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from idea_scout.definitions import (  # noqa: E402
    DEFAULT_INSTRUCTIONS,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
)

_CHAT_AGENTS_PATH = "/api/v1/admin/plugins/idea-scout/chat-agents"

_DEFAULT_RESEARCH_MODEL = os.environ.get("IDEA_SCOUT_RESEARCH_MODEL", "anthropic/claude-sonnet-4")
_DEFAULT_SYNTHESIS_MODEL = os.environ.get("IDEA_SCOUT_SYNTHESIS_MODEL", "anthropic/claude-opus-4-8")


def payloads() -> list[dict[str, Any]]:
    """One row per agent role, carrying the built-in prompt verbatim.

    Seeding the *same* text the code falls back to means turning configuration on
    changes nothing observable — the usual trap being a seed that quietly differs
    from the default and shifts behaviour the moment it lands.
    """
    rows = [
        {
            "agent_key": name,
            "agent_name": name,
            "role": name,
            "system_prompt": DEFAULT_INSTRUCTIONS[name],
            "model": _DEFAULT_RESEARCH_MODEL,
            "required_group": "founder",
            "active": True,
        }
        for name in RESEARCH_AGENT_NAMES
    ]
    rows.append(
        {
            "agent_key": SYNTHESIS_AGENT_NAME,
            "agent_name": SYNTHESIS_AGENT_NAME,
            "role": SYNTHESIS_AGENT_NAME,
            "system_prompt": DEFAULT_INSTRUCTIONS[SYNTHESIS_AGENT_NAME],
            "model": _DEFAULT_SYNTHESIS_MODEL,
            "required_group": "founder",
            "active": True,
        }
    )
    return rows


def _request(method: str, url: str, token: str, body: dict | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return json.loads(resp.read() or b"null")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print, change nothing")
    args = parser.parse_args()

    rows = payloads()
    if args.dry_run:
        print(json.dumps(rows, indent=2))
        return 0

    api = os.environ.get("CORE_API_URL", "").rstrip("/")
    token = os.environ.get("ADMIN_BEARER_TOKEN", "")
    if not api or not token:
        print("CORE_API_URL and ADMIN_BEARER_TOKEN are both required.", file=sys.stderr)
        return 2

    url = f"{api}{_CHAT_AGENTS_PATH}"
    created = 0
    for row in rows:
        try:
            _request("POST", url, token, row)
            created += 1
        except urllib.error.HTTPError as exc:
            if exc.code == 409:  # already seeded — leave the admin's version alone
                continue
            print(f"Failed on {row['agent_key']}: {exc.code} {exc.reason}", file=sys.stderr)
            return 1

    print(f"Created {created} agent config row(s); {len(rows) - created} already present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
