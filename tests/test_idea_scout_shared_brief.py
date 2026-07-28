"""The founder profile reaches synthesis only because all three briefs are identical.

biffo-plugin-idea-scout#26 was fixed upstream: `agent_fan_in` forwards, as
`input_payload["context"]`, the keys that **every** contributing sibling carries
with an equal value (biffo-template#783). The synthesis agent gets the founder's
profile, build type and complexity that way, and its prompt has always claimed it
does.

This plugin satisfies that precondition **by accident**. `start_run` computes
`brief` once, before the loop, and hands the same object to all three research
runs. Make the briefs angle-specific — an obvious future improvement, since the
three agents already have distinct prompts — and the intersection becomes empty,
the key is omitted, and synthesis silently goes back to inferring founder-fit
second-hand from the research text.

That regression would be **invisible**: no test fails, no error is raised
(`_shared_input` returning `{}` is a legitimate outcome it handles by design),
and the agent still produces plausible founder-fitted prose. Exactly the shape
#26 described — *"the prompt and the payload disagree, and the output still looks
fine"*.

So these tests re-implement the upstream intersection rule locally and assert the
founder-fit data survives it. They fail the moment the briefs diverge, in this
repo, without needing the engine (issue #29).
"""

from __future__ import annotations

from typing import Any

import pytest
from fakes import FakeCoreGateway
from idea_scout.definitions import RESEARCH_AGENT_NAMES
from idea_scout.service import IdeaScoutService

OWNER = "founder-sub-abc"


def _service(core: FakeCoreGateway) -> IdeaScoutService:
    return IdeaScoutService(core, research_model="research-m", synthesis_model="synthesis-m")


def _shared_input(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """`agent_fan_in._shared_input`, reproduced verbatim in behaviour.

    Copied rather than imported: the orchestrator is a Biffo *plugin* in the
    template repo, not a dependency of this one, so there is nothing to import.
    Copying is the cost of testing a contract that crosses a repo boundary — and
    the contract is four lines, stated in `_shared_input`'s docstring as *"only
    keys every contributing sibling carries with an equal value survive"*.

    If the upstream rule changes, this copy is wrong and these tests pass while
    production breaks. That is a real limitation of the approach and is why the
    tests below also assert the *reason* the rule holds (one brief object shared
    by all three), not only its current outcome.
    """
    dicts = [p for p in payloads if isinstance(p, dict)]
    if not dicts:
        return {}
    first, *rest = dicts
    return {
        key: value
        for key, value in first.items()
        if all(key in other and other[key] == value for other in rest)
    }


async def _research_payloads(core: FakeCoreGateway, *, complexity: int = 3) -> list[dict[str, Any]]:
    await _service(core).start_run(owner_sub=OWNER, build_type="micro-saas", complexity=complexity)
    research = [r for r in core.requested if r["agent_name"] in RESEARCH_AGENT_NAMES]
    assert len(research) == len(RESEARCH_AGENT_NAMES), research
    return [r["input_payload"] for r in research]


@pytest.mark.asyncio
async def test_the_founder_fit_data_survives_the_fan_ins_intersection():
    """The property #26 depends on, asserted through the upstream rule rather
    than through the loop's current shape."""
    core = FakeCoreGateway()
    shared = _shared_input(await _research_payloads(core))

    assert shared, "no key is common to all three briefs — synthesis would receive no context"
    brief = shared.get("brief")
    assert brief is not None, (
        f"the brief did not survive the intersection; shared keys: {list(shared)}"
    )

    # The three things #26 named as missing.
    assert "profile" in brief, brief
    assert "build_type" in brief, brief
    assert "complexity" in brief, brief


@pytest.mark.asyncio
async def test_every_research_agent_is_briefed_identically():
    """The *reason* the rule holds, asserted directly.

    The test above would still pass if two of three agents shared a brief and the
    third diverged in a key the other two lack — the intersection would shrink
    but might keep `brief`. This one fails on any divergence at all, which is the
    condition `_shared_input` actually depends on.
    """
    payloads = await _research_payloads(FakeCoreGateway())
    first, *rest = payloads

    for other in rest:
        assert other == first, (
            "research briefs have diverged. That is a reasonable thing to want — "
            "the three agents have distinct prompts — but it silently removes the "
            "founder profile from synthesis (#26/#29). If you need per-angle "
            "briefs, split the payload into a shared portion and an angle "
            "portion, e.g. {'shared': {...}, 'angle': {...}}, so the shared part "
            "still survives _shared_input's intersection."
        )


@pytest.mark.asyncio
async def test_an_empty_profile_still_leaves_shared_context_for_synthesis():
    """A founder who has saved no profile must not collapse the context entirely.

    `_build_brief` omits the `profile` key when the profile is empty — deliberately,
    so the model is not invited to invent a founder. Build type and complexity
    still apply, and synthesis still needs them.
    """
    core = FakeCoreGateway()
    core.profile = type(core.profile)()  # a default, empty UserProfile

    shared = _shared_input(await _research_payloads(core))
    brief = shared.get("brief")

    assert brief is not None, "an empty profile emptied the whole shared context"
    assert "profile" not in brief, "an empty profile should be omitted, not sent as nulls"
    assert brief["build_type"]["key"] == "micro-saas"
    assert brief["complexity"]


@pytest.mark.asyncio
async def test_the_guard_would_notice_a_divergent_brief():
    """Guards the guard.

    Every assertion above passes trivially if `_shared_input` were implemented
    wrongly here — e.g. returning its first argument unchanged. Feed it briefs
    that genuinely differ and confirm the intersection actually drops the key,
    so the tests above are detecting something rather than asserting a tautology.
    """
    identical = [{"brief": {"profile": {"x": 1}}}, {"brief": {"profile": {"x": 1}}}]
    diverged = [{"brief": {"profile": {"x": 1}}}, {"brief": {"profile": {"x": 2}}}]
    partial = [{"brief": {"a": 1}, "angle": "community"}, {"brief": {"a": 1}, "angle": "narrative"}]

    assert "brief" in _shared_input(identical)
    assert "brief" not in _shared_input(diverged), "divergent briefs must not survive"
    assert _shared_input(partial) == {"brief": {"a": 1}}, "per-angle keys must be dropped"
