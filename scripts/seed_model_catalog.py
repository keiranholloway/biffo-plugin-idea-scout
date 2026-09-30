#!/usr/bin/env python3
"""Seed the research-model catalog founders pick from.

**Nothing works without this.** ``start_run`` validates any ``research_model``
override against the *live* ``idea_scout_model_catalog`` table (active and
``web_capable``), and the run form pre-selects the catalog's ``is_default`` row.
With no row for ``DEFAULT_RESEARCH_MODEL`` a run is rejected with 422
"Research model not available". Same class of silent prerequisite as
``seed_build_types.py``.

This is the starting set, not a fixed enum: the table is admin-managed through
generic CRUD. Re-running this does not undo an admin's edits; it only creates
rows whose ``model_id`` is absent.

Usage:
    CORE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com \
    ADMIN_BEARER_TOKEN=<a real Cognito admin id/access token> \
    python scripts/seed_model_catalog.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from idea_scout.definitions import DEFAULT_RESEARCH_MODEL

_MODEL_CATALOG_PATH = "/api/v1/plugins/idea-scout/idea_scout_model_catalog"

#: The starting models. The default research model MUST be present, active,
#: web-capable and the default.
MODELS: list[dict[str, Any]] = [
    {
        "model_id": DEFAULT_RESEARCH_MODEL,
        "label": "Claude Sonnet 4 (web search)",
        "active": True,
        "is_default": True,
        "web_capable": True,
    },
]


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

    if args.dry_run:
        print(json.dumps(MODELS, indent=2))
        return 0

    api = os.environ.get("CORE_API_URL", "").rstrip("/")
    token = os.environ.get("ADMIN_BEARER_TOKEN", "")
    if not api or not token:
        print("CORE_API_URL and ADMIN_BEARER_TOKEN are both required.", file=sys.stderr)
        return 2

    url = f"{api}{_MODEL_CATALOG_PATH}"
    try:
        existing = _request("GET", url, token) or []
    except urllib.error.HTTPError as exc:
        print(f"Could not list model catalog: {exc.code} {exc.reason}", file=sys.stderr)
        return 1

    # Idempotent by model_id (unique per tenant). Generic CRUD has no upsert.
    have = {row.get("model_id") for row in existing}
    created = 0
    for model in MODELS:
        if model["model_id"] in have:
            continue
        try:
            _request("POST", url, token, model)
        except urllib.error.HTTPError as exc:
            print(f"Failed on {model['model_id']}: {exc.code} {exc.reason}", file=sys.stderr)
            return 1
        created += 1

    skipped = len(MODELS) - created
    print(f"Created {created} model(s); {skipped} already present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
