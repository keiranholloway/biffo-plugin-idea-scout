#!/usr/bin/env python3
"""Seed the workflow definition that makes an Idea Scout run finish unattended.

Idea Scout fans out to three research agents under one causation chain. Nothing
in the plugin then watches them — the orchestration engine does, via an
``agent_fan_in`` action (biffo-template#657) that fires the synthesis agent once
every research run in the chain is terminal.

Core resolves the synthesis agent's ``instructions`` and ``model`` from the
plugin's seeded config at agent-run creation time, so those fields are no longer
frozen into the workflow definition — an admin's edits to the stored prompt and
model now take effect immediately.

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
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    SYNTHESIS_MAX_TURNS,
)

WORKFLOW_NAME = "Idea Scout — synthesise once research completes"

#: Core mounts the orchestration router at `/api/v1/orchestration`, NOT under
#: `/api/v1/admin`. This carried a stray `admin/` segment until 2026-08-12,
#: which meant the script 404'd on every run in every environment and had
#: therefore never once seeded a definition — so any scout run that finished
#: did so on something other than this workflow.
#:
#: Verified in Core's source rather than guessed: the workflow-CRUD router
#: declares `prefix="/orchestration/workflows"`
#: (tabsii-platform `services/api/src/api/routers/orchestration.py:83`) and is
#: mounted with `prefix="/api/v1"` (`services/api/src/api/main.py:117`). The
#: `/api/v1/admin/orchestration` router is a different one that exposes only
#: `/test` (`services/api/src/api/routers/admin/orchestration.py:39,44`), so
#: the `admin/` variant 404s exactly like a route that never existed.
#:
#: The sibling plugin `biffo-plugin-marketing` hit and fixed this identical
#: line first (its #61), and measured it against deployed dev on 2026-08-11:
#: `/api/v1/orchestration/workflows` -> 200 with a valid admin token, the
#: `admin/` variant -> 404.
_DEFINITIONS_PATH = "/api/v1/orchestration/workflows"


def definition() -> dict:
    """The workflow this plugin needs in order to finish a run on its own.

    Triggered by every ``agent.run.completed``: the fan-in action itself decides
    whether the event belongs to a chain it cares about, and no-ops otherwise.
    That is deliberate — filtering by agent name in the trigger would still fire
    three times per run (once per research agent), and the action's own
    all-siblings-terminal check is what collapses those three into one.

    Carries no ``instructions`` and no ``model``: Core resolves both from the
    plugin's seeded config at agent-run creation, which is what makes an admin's
    edit take effect. This function therefore takes **no model argument** — one
    would be silently ignored, which is the defect (idea-scout#64) this whole
    change removes rather than relocates.
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
    args = parser.parse_args()

    payload = definition()

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
