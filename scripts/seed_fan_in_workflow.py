#!/usr/bin/env python3
"""Seed the workflow definition that makes an Idea Scout run finish unattended.

Idea Scout fans out to three research agents under one causation chain. Nothing
in the plugin then watches them — the orchestration engine does, via an
``agent_fan_in`` action (biffo-template#657) that fires the synthesis agent once
every research run in the chain is terminal.

**Without this definition, a scout run never leaves ``researching``.** The three
research agents still run and still bill; nothing reconciles them. That is the
whole failure mode this script exists to prevent, and it is silent — which is
why it is called out here rather than left to a deploy runbook.

Run this ONCE per environment, by an operator with real Cognito admin
credentials, after the plugin is installed. It is idempotent: an existing
definition with the same name is left alone unless ``--replace`` is passed.

Usage:
    CORE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com \
    ADMIN_BEARER_TOKEN=<a real Cognito admin id/access token> \
    python scripts/seed_fan_in_workflow.py [--dry-run] [--replace]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

# Importable without the package installed, so an operator can run this from a
# checkout without a uv sync first.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from idea_scout.definitions import (  # noqa: E402
    DEFAULT_SYNTHESIS_MODEL,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    SYNTHESIS_INSTRUCTIONS,
    SYNTHESIS_MAX_TURNS,
)

WORKFLOW_NAME = "Idea Scout — synthesise once research completes"

_DEFINITIONS_PATH = "/api/v1/admin/orchestration/workflows"


def definition(*, model: str) -> dict:
    """The workflow this plugin needs in order to finish a run on its own.

    Triggered by every ``agent.run.completed``: the fan-in action itself decides
    whether the event belongs to a chain it cares about, and no-ops otherwise.
    That is deliberate — filtering by agent name in the trigger would still fire
    three times per run (once per research agent), and the action's own
    all-siblings-terminal check is what collapses those three into one.
    """
    return {
        "name": WORKFLOW_NAME,
        "trigger_source": "biffo.core",
        "trigger_detail_type": "agent.run.completed",
        "action_type": "agent_fan_in",
        "action_config": {
            # The set to wait for. These names must match what the plugin
            # actually requests — see idea_scout.definitions.
            "expect_agents": ",".join(RESEARCH_AGENT_NAMES),
            "agent_name": SYNTHESIS_AGENT_NAME,
            "instructions": SYNTHESIS_INSTRUCTIONS,
            "model": model,
            "max_turns": SYNTHESIS_MAX_TURNS,
        },
        "enabled": True,
    }


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
    parser.add_argument(
        "--replace",
        action="store_true",
        help="overwrite an existing definition of the same name",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("IDEA_SCOUT_SYNTHESIS_MODEL", DEFAULT_SYNTHESIS_MODEL),
        help="model for the synthesis agent",
    )
    args = parser.parse_args()

    payload = definition(model=args.model)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    api = os.environ.get("CORE_API_URL", "").rstrip("/")
    token = os.environ.get("ADMIN_BEARER_TOKEN", "")
    if not api or not token:
        print("CORE_API_URL and ADMIN_BEARER_TOKEN are both required.", file=sys.stderr)
        return 2

    url = f"{api}{_DEFINITIONS_PATH}"
    try:
        existing = _request("GET", url, token) or []
    except urllib.error.HTTPError as exc:
        print(f"Could not list workflows: {exc.code} {exc.reason}", file=sys.stderr)
        return 1

    match = next(
        (w for w in existing if w.get("name") == WORKFLOW_NAME),
        None,
    )
    if match and not args.replace:
        print(f"Already seeded (id {match.get('id')}). Pass --replace to overwrite.")
        return 0

    try:
        if match:
            _request("PUT", f"{url}/{match['id']}", token, payload)
            print(f"Replaced workflow {match['id']}.")
        else:
            created = _request("POST", url, token, payload)
            print(f"Created workflow {(created or {}).get('id')}.")
    except urllib.error.HTTPError as exc:
        print(f"Failed: {exc.code} {exc.reason} — {exc.read()[:400]!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
