"""The seed data. Two of these three scripts are hard prerequisites — the plugin
deploys clean and is unusable without them — so their contents are asserted
rather than trusted.
"""

from __future__ import annotations

from idea_scout.definitions import (
    DEFAULT_INSTRUCTIONS,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
)
from scripts.seed_agent_config import payloads
from scripts.seed_build_types import BUILD_TYPES

# ── Build types ──────────────────────────────────────────────────────────────


def test_the_starting_categories_have_unique_keys():
    """The key is what a run stores and what the founder's request is validated
    against; a duplicate would make one of them unreachable."""
    keys = [t["key"] for t in BUILD_TYPES]
    assert len(set(keys)) == len(keys)


def test_every_category_has_a_description():
    """Not decoration — the description goes into the research brief, so a blank
    one silently makes the agents' scoping worse."""
    for build_type in BUILD_TYPES:
        assert build_type["description"].strip(), build_type["key"]


def test_every_category_is_ordered():
    orders = [t["sort_order"] for t in BUILD_TYPES]
    assert len(set(orders)) == len(orders)
    assert orders == sorted(orders)


def test_keys_are_url_and_storage_safe():
    for build_type in BUILD_TYPES:
        key = build_type["key"]
        assert key == key.lower()
        assert " " not in key
        assert len(key) <= 64


# ── Agent config ─────────────────────────────────────────────────────────────


def test_a_row_is_seeded_for_every_agent_role():
    keys = {row["agent_key"] for row in payloads()}
    assert keys == {*RESEARCH_AGENT_NAMES, SYNTHESIS_AGENT_NAME}


def test_the_seeded_prompt_is_exactly_the_built_in_default():
    """Turning configuration on must change nothing observable. A seed that
    quietly differs from the fallback shifts behaviour the moment it lands, and
    the diff is invisible to whoever runs the script."""
    for row in payloads():
        assert row["system_prompt"] == DEFAULT_INSTRUCTIONS[row["agent_key"]]


def test_every_seeded_row_is_active():
    assert all(row["active"] for row in payloads())
