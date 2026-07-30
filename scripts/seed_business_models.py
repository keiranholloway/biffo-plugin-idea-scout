#!/usr/bin/env python3
"""Seed the business-model categories a founder can scope a scout to.

Unlike ``seed_build_types.py``, an empty table here does **not** break the
plugin: the business model is optional and ``start_run`` accepts ``None`` as a
real answer ("no preference"). An empty table simply means the picker offers
nothing, so runs are scoped by build type alone — degraded, not broken.

These are a starting set, not a fixed enum: the table is admin-managed through
generic CRUD, so an admin can add, relabel, reorder or deactivate categories
without a code change. Re-running does not undo an admin's edits; it only
creates categories whose ``key`` is absent.

**No valuation figures belong in these descriptions.** The taxonomy was derived
from a corpus of marketplace *asking* prices containing no confirmed sales, so a
multiple printed here would read to a founder as a valuation it is not — and
published asking multiples in that corpus run well above what comparable deals
actually close at. ``tests/test_idea_scout_seed_business_models.py`` fails if a
currency symbol or a multiple ever appears in this file's descriptions.

Usage:
    CORE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com \
    ADMIN_BEARER_TOKEN=<a real Cognito admin id/access token> \
    python scripts/seed_business_models.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

_BUSINESS_MODELS_PATH = "/api/v1/plugins/idea-scout/business-models"

#: The starting categories. `description` is not decoration — it goes into the
#: research brief, so it says what the revenue mechanism implies for *scope* and
#: what it demands of the founder, not merely what it is.
#:
#: The set was rationalised from 40 raw strings observed across ~283 real
#: marketplace listings, collapsed to the mechanism that most changes what you
#: build. Combinations resolve to their dominant mechanism, and `freemium` folds
#: into `subscription` deliberately — it is a go-to-market on top of a
#: subscription, not a distinct way of earning money.
BUSINESS_MODELS: list[dict[str, Any]] = [
    {
        "key": "subscription",
        "label": "Subscription / SaaS",
        "description": (
            "Recurring payment for continued access. Revenue compounds but so does "
            "the retention obligation — the product has to stay worth paying for "
            "every month, which favours an ongoing job over a one-off task."
        ),
        "sort_order": 1,
    },
    {
        "key": "one-off-purchase",
        "label": "One-off purchase",
        "description": (
            "Paid once, owned outright — a tool, template, app or asset. No churn to "
            "manage and no support tail assumed, but revenue restarts from zero every "
            "month, so distribution has to keep working indefinitely."
        ),
        "sort_order": 2,
    },
    {
        "key": "usage-credits",
        "label": "Usage / credits",
        "description": (
            "Charged per action, generation or unit consumed. Aligns price with "
            "value and suits workloads with a real marginal cost, but revenue is "
            "lumpy and the unit economics must survive the underlying cost moving."
        ),
        "sort_order": 3,
    },
    {
        "key": "lifetime-deal",
        "label": "Lifetime deal (LTD)",
        "description": (
            "One payment for perpetual access, usually to seed early adoption. Pulls "
            "revenue forward at the cost of every future renewal, and the support "
            "obligation outlives the payment — a deliberate trade, not a default."
        ),
        "sort_order": 4,
    },
    {
        "key": "marketplace-commission",
        "label": "Marketplace commission",
        "description": (
            "A cut of transactions between two sides. The software is rarely the "
            "hard part; bootstrapping the first side is, and the model only works "
            "where that path is plausible and the transaction is worth taxing."
        ),
        "sort_order": 5,
    },
    {
        "key": "advertising",
        "label": "Advertising / sponsorship",
        "description": (
            "Monetised through advertisers or sponsors rather than users. Demands "
            "audience scale before any revenue appears, so it suits content and "
            "media positions far more than tools."
        ),
        "sort_order": 6,
    },
    {
        "key": "affiliate",
        "label": "Affiliate / referral",
        "description": (
            "Paid a referral fee for sending qualified demand elsewhere. Cheap to "
            "start and needs no billing of your own, but the economics belong to "
            "someone else's programme and can be changed without notice."
        ),
        "sort_order": 7,
    },
    {
        "key": "licensing",
        "label": "Licensing",
        "description": (
            "Licensing the technology, data or brand to other businesses to embed. "
            "Few customers, larger contracts, longer sales cycles — a B2B motion "
            "with procurement attached rather than a self-serve one."
        ),
        "sort_order": 8,
    },
    {
        "key": "services",
        "label": "Services / done-for-you",
        "description": (
            "Revenue from delivery — implementation, agency or done-for-you work, "
            "often alongside a product. Predictable and immediate, but it scales "
            "with hours rather than with software."
        ),
        "sort_order": 9,
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
        print(json.dumps(BUSINESS_MODELS, indent=2))
        return 0

    api = os.environ.get("CORE_API_URL", "").rstrip("/")
    token = os.environ.get("ADMIN_BEARER_TOKEN", "")
    if not api or not token:
        print("CORE_API_URL and ADMIN_BEARER_TOKEN are both required.", file=sys.stderr)
        return 2

    url = f"{api}{_BUSINESS_MODELS_PATH}"
    try:
        existing = _request("GET", url, token) or []
    except urllib.error.HTTPError as exc:
        print(f"Could not list business models: {exc.code} {exc.reason}", file=sys.stderr)
        return 1

    # Idempotent by key. Generic CRUD has no upsert — every POST creates a row —
    # so a blind re-run would duplicate every category.
    have = {row.get("key") for row in existing}
    created = 0
    for model in BUSINESS_MODELS:
        if model["key"] in have:
            continue
        try:
            _request("POST", url, token, {**model, "active": True})
        except urllib.error.HTTPError as exc:
            print(f"Failed on {model['key']}: {exc.code} {exc.reason}", file=sys.stderr)
            return 1
        created += 1

    skipped = len(BUSINESS_MODELS) - created
    print(f"Created {created} business model(s); {skipped} already present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
