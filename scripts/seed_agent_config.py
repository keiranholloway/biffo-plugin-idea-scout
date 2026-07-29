#!/usr/bin/env python3
"""Seed the admin-editable prompt/model config for Idea Scout's four agents.

This is a manual entry point for operators with admin credentials. The plugin
guarantees rows exist at startup via ``seed_config_payloads()``, so editing this
row now takes effect immediately for synthesis — it is no longer frozen into the
workflow.

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
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    seed_config_payloads,
)

_CHAT_AGENTS_PATH = "/api/v1/admin/plugins/idea-scout/chat-agents"

# Environment overrides the built-in defaults, but always fall back to the
# constants in definitions.py, not a separate hardcoded copy. This ensures
# the seed, admin_app, and app.py all use the same values.
_DEFAULT_RESEARCH_MODEL = os.environ.get("IDEA_SCOUT_RESEARCH_MODEL", DEFAULT_RESEARCH_MODEL)
_DEFAULT_SYNTHESIS_MODEL = os.environ.get("IDEA_SCOUT_SYNTHESIS_MODEL", DEFAULT_SYNTHESIS_MODEL)


def payloads() -> list[dict[str, Any]]:
    """One row per agent role, built by the shared payload builder.

    Uses environment overrides if set, falling back to the built-in constants.
    """
    return seed_config_payloads(
        research_model=_DEFAULT_RESEARCH_MODEL,
        synthesis_model=_DEFAULT_SYNTHESIS_MODEL,
    )


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
