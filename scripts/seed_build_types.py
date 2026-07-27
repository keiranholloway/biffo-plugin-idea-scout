#!/usr/bin/env python3
"""Seed the build-type categories a founder picks from.

**Nothing works without this.** ``start_run`` validates the requested build type
against the *active* list, so with an empty table every run request is rejected
and the founder's picker is empty — the plugin deploys clean and is unusable.
Same class of silent prerequisite as ``seed_fan_in_workflow.py``.

These are the starting set, not a fixed enum: the table is admin-managed through
generic CRUD, so an admin can add, relabel, reorder or deactivate categories
without a code change (that was the design decision — see the epic). Re-running
this does not undo an admin's edits; it only creates categories whose ``key`` is
absent.

Usage:
    CORE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com \
    ADMIN_BEARER_TOKEN=<a real Cognito admin id/access token> \
    python scripts/seed_build_types.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

_BUILD_TYPES_PATH = "/api/v1/plugins/idea-scout/build-types"

#: The starting categories. `description` is not decoration — it goes into the
#: research brief, so it should say what the category implies for *scope*, not
#: just what it is. `sort_order` puts the smallest commitment first, because a
#: founder browsing is more likely to want the narrow end.
BUILD_TYPES: list[dict[str, Any]] = [
    {
        "key": "browser-extension",
        "label": "Browser Extension",
        "description": (
            "A focused tool that augments a site or workflow the user is already in. "
            "Narrow scope, fast to build, distribution through an extension store."
        ),
        "sort_order": 1,
    },
    {
        "key": "micro-saas",
        "label": "MicroSaaS",
        "description": (
            "One narrow job done well for a specific audience, usually solo-maintainable. "
            "Small surface area, subscription pricing, little to no sales motion."
        ),
        "sort_order": 2,
    },
    {
        "key": "mobile-app",
        "label": "Mobile Application",
        "description": (
            "A phone-first product where the mobile context itself matters — camera, "
            "location, notifications, offline. App-store distribution and review cycles."
        ),
        "sort_order": 3,
    },
    {
        "key": "full-saas",
        "label": "Full SaaS Application",
        "description": (
            "A broad multi-workflow product with accounts, roles and integrations. "
            "Substantial to build and to sell; expect a real go-to-market, not just a launch."
        ),
        "sort_order": 4,
    },
    {
        "key": "marketplace",
        "label": "Marketplace or Network",
        "description": (
            "Two or more sides that need each other. The hard part is not the software "
            "but bootstrapping the first side; only worth it where that path is plausible."
        ),
        "sort_order": 5,
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
        print(json.dumps(BUILD_TYPES, indent=2))
        return 0

    api = os.environ.get("CORE_API_URL", "").rstrip("/")
    token = os.environ.get("ADMIN_BEARER_TOKEN", "")
    if not api or not token:
        print("CORE_API_URL and ADMIN_BEARER_TOKEN are both required.", file=sys.stderr)
        return 2

    url = f"{api}{_BUILD_TYPES_PATH}"
    try:
        existing = _request("GET", url, token) or []
    except urllib.error.HTTPError as exc:
        print(f"Could not list build types: {exc.code} {exc.reason}", file=sys.stderr)
        return 1

    # Idempotent by key. Generic CRUD has no upsert — every POST creates a row —
    # so a blind re-run would duplicate every category.
    have = {row.get("key") for row in existing}
    created = 0
    for build_type in BUILD_TYPES:
        if build_type["key"] in have:
            continue
        try:
            _request("POST", url, token, {**build_type, "active": True})
        except urllib.error.HTTPError as exc:
            print(f"Failed on {build_type['key']}: {exc.code} {exc.reason}", file=sys.stderr)
            return 1
        created += 1

    skipped = len(BUILD_TYPES) - created
    print(f"Created {created} build type(s); {skipped} already present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
