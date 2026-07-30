"""The business-model seed set, and the guard that keeps valuation figures out.

The taxonomy behind these categories was derived from a corpus of marketplace
*asking* prices with no confirmed sales in it. A multiple or price printed in a
founder-facing description would therefore read as a valuation it is not — and
published asking multiples in that corpus run well above what comparable deals
actually close at. That constraint is easy to forget in six months, so it is a
test rather than a comment.
"""

from __future__ import annotations

import re

from _scripts import load_script

seed = load_script("seed_business_models")
MODELS = seed.BUSINESS_MODELS

#: Currency symbols, and a multiple written either as "4x" or "4×".
#:
#: The trailing lookahead is deliberate and was a real bug: a ``\b`` here fails to
#: match "5.8× revenue", because ``×`` (U+00D7) is not a word character and neither
#: is the space after it, so there is no boundary between them. The guard silently
#: passed on the exact character the source table used. A negative lookahead for an
#: alphanumeric works for both spellings and still rejects "10xyz".
_MONEY = re.compile(r"[$£€]|\b\d+(?:\.\d+)?\s*[x×](?![a-z0-9])", re.IGNORECASE)


def test_seeds_the_nine_rationalised_categories():
    assert [m["key"] for m in MODELS] == [
        "subscription",
        "one-off-purchase",
        "usage-credits",
        "lifetime-deal",
        "marketplace-commission",
        "advertising",
        "affiliate",
        "licensing",
        "services",
    ]


def test_the_valuation_guard_actually_catches_violations():
    """Guards the guard. Without this the pattern can rot into one that matches
    nothing and the real test below passes vacuously — which it did, on "5.8×"."""
    for offending in (
        "Typically trades at 4.0x revenue.",
        "Sellers ask around 5.8× revenue.",
        "Deals close near 2.8 x profit.",
        "Median asking price $12,000.",
        "Around £9,000 in this category.",
    ):
        assert _MONEY.search(offending) is not None, offending
    for clean in (
        "Recurring payment for continued access; the retention obligation compounds.",
        "A cut of transactions between two sides, where bootstrapping is the hard part.",
    ):
        assert _MONEY.search(clean) is None, clean


def test_no_description_carries_a_valuation_figure():
    """The load-bearing guard. See this module's docstring."""
    for model in MODELS:
        found = _MONEY.search(model["description"])
        assert found is None, (
            f"{model['key']} description contains what looks like a valuation "
            f"figure ({found.group(0)!r}). Founder-facing copy must carry no "
            "price or multiple — the corpus behind this taxonomy has no sold data."
        )


def test_every_category_is_complete_and_ordered():
    orders = [m["sort_order"] for m in MODELS]
    assert orders == sorted(orders), "sort_order must ascend in declaration order"
    assert len(set(orders)) == len(orders), "sort_order must be unique"
    for model in MODELS:
        assert model["label"].strip()
        # The description reaches the research brief, so an empty one silently
        # degrades every run scoped to that category.
        assert len(model["description"].strip()) > 40, model["key"]


def test_keys_are_stable_slugs():
    for model in MODELS:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", model["key"]), model["key"]
        assert len(model["key"]) <= 64


def test_dry_run_prints_without_network(capsys):
    """--dry-run must not require CORE_API_URL or a token; it is how an operator
    reviews the set before touching an environment."""
    import sys

    argv = sys.argv
    sys.argv = ["seed_business_models.py", "--dry-run"]
    try:
        assert seed.main() == 0
    finally:
        sys.argv = argv
    assert "subscription" in capsys.readouterr().out
