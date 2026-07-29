"""Weight preferences: validated, snapshotted, and carried to every agent (#34).

A founder can say what *shape* of business they want, separately from who they
are (the profile) and what form it takes (the build type). Two founders with
identical profiles and identical build-type/complexity choices previously got an
identical brief.

The design decision these tests encode is that preferences are **weights, not
filters** — the plumbing has to deliver them to the agents intact, and it is the
prompts, not the code, that decide how much they count.
"""

from __future__ import annotations

import pytest
from fakes import FakeCoreGateway

from idea_scout.definitions import (
    PREFERENCE_KEYS,
    PREFERENCES,
    preference_brief,
    seed_config_payloads,
)
from idea_scout.service import IdeaScoutService, UnknownPreferenceError

OWNER = "founder-sub-abc"


def _service(core: FakeCoreGateway) -> IdeaScoutService:
    return IdeaScoutService(core, research_model="research-m", synthesis_model="synthesis-m")


def _seed_core(core: FakeCoreGateway) -> None:
    """Seed the gateway with agent config payloads, insert-if-absent."""
    payload = seed_config_payloads(research_model="research-m", synthesis_model="synthesis-m")
    for row in payload:
        role = row["role"]
        if role not in core.configs:
            core.configs[role] = {
                "system_prompt": row["system_prompt"],
                "model": row["model"],
            }


async def _start(core: FakeCoreGateway, preferences: list[str] | None = None):
    _seed_core(core)
    return await _service(core).start_run(
        owner_sub=OWNER, build_type="micro-saas", complexity=3, preferences=preferences
    )


# ── the list itself ──────────────────────────────────────────────────────────


def test_every_preference_has_a_direction_the_prompts_understand():
    # The prompts branch on `direction`; a third value would be silently ignored
    # by them and silently accepted here.
    assert {p["direction"] for p in PREFERENCES} == {"prefer", "avoid"}


def test_keys_are_unique_and_url_safe():
    keys = [p["key"] for p in PREFERENCES]
    assert len(keys) == len(set(keys)), "a duplicate key would make one unreachable"
    assert all(k.replace("-", "").isalnum() and k.islower() for k in keys), keys


def test_the_ten_requested_dimensions_are_all_present():
    # Named explicitly so removing one is a deliberate act with a failing test,
    # not a quiet edit to a tuple.
    assert PREFERENCE_KEYS == {
        "recurring-revenue",
        "underserved-niches",
        "existing-expertise",
        "low-support-burden",
        "rapid-validation",
        "organic-distribution",
        "regulated-markets",
        "two-sided-marketplaces",
        "paid-advertising",
        "platform-dependence",
    }


def test_preference_brief_uses_declaration_order_not_client_order():
    """A payload whose meaning depends on client ordering is one two clients can
    disagree about."""
    forward = preference_brief(["recurring-revenue", "regulated-markets"])
    reversed_ = preference_brief(["regulated-markets", "recurring-revenue"])
    assert forward == reversed_
    assert [p["key"] for p in forward] == ["recurring-revenue", "regulated-markets"]


def test_preference_brief_drops_keys_no_prompt_knows():
    # Second line of defence: the service rejects unknown keys at the boundary,
    # but a run stored before the list changed must not brief an agent on a
    # preference the prompts cannot weigh.
    assert preference_brief(["recurring-revenue", "invented"]) == [
        {"key": "recurring-revenue", "direction": "prefer", "label": "Recurring revenue"}
    ]


# ── the service ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unknown_key_is_rejected_loudly_not_dropped():
    """A client sending a stale key must learn it is stale, rather than getting a
    run that quietly ignored half its input."""
    with pytest.raises(UnknownPreferenceError) as exc:
        await _start(FakeCoreGateway(), ["recurring-revenue", "prefer-purple"])
    assert "prefer-purple" in str(exc.value)


@pytest.mark.asyncio
async def test_no_preferences_is_valid_and_is_not_defaulted_to_anything():
    """Expressing none is a real answer. A default would shape every result from
    an input the founder never made — the invisible-input failure this plugin has
    already had twice (#26, #29)."""
    run = await _start(FakeCoreGateway(), None)
    assert run.preferences == []


@pytest.mark.asyncio
async def test_the_selection_is_snapshotted_on_the_run():
    core = FakeCoreGateway()
    run = await _start(core, ["recurring-revenue", "regulated-markets"])
    # Snapshotted like profile_snapshot, so the run stays explicable after the
    # founder changes their mind.
    assert run.preferences == ["recurring-revenue", "regulated-markets"]


@pytest.mark.asyncio
async def test_preferences_reach_every_research_agent_identically():
    """The condition #29 guards: the brief must stay identical across siblings or
    `agent_fan_in` drops it and synthesis never sees it."""
    core = FakeCoreGateway()
    await _start(core, ["recurring-revenue"])

    briefs = [r["input_payload"]["brief"] for r in core.requested if "brief" in r["input_payload"]]
    assert len(briefs) == 3
    assert all(b == briefs[0] for b in briefs)
    assert briefs[0]["preferences"] == [
        {"key": "recurring-revenue", "direction": "prefer", "label": "Recurring revenue"}
    ]


@pytest.mark.asyncio
async def test_an_empty_selection_omits_the_key_rather_than_sending_an_empty_list():
    """Same reasoning as an empty profile: an empty list invites the model to
    reason about a preference set that does not exist."""
    core = FakeCoreGateway()
    await _start(core, [])

    brief = next(
        r["input_payload"]["brief"] for r in core.requested if "brief" in r["input_payload"]
    )
    assert "preferences" not in brief
