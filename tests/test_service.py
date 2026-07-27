"""Tests for the orchestration — the fan-out, the fan-in, and every way they
can go wrong.

The state machine advances on the founder's poll (see service.py's docstring),
so most of these drive it by finishing scripted agent runs and then calling
``get_run``/``get_candidates`` — exactly as the UI's polling loop does.
"""

from __future__ import annotations

import pytest
from fakes import (
    FakeCoreGateway,
    candidate_payload,
    candidates_message,
    findings_message,
)

from idea_scout import models as m
from idea_scout.definitions import (
    MAX_CANDIDATES,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
)
from idea_scout.models import BuildType, UserProfile
from idea_scout.service import (
    IdeaScoutService,
    InvalidComplexityError,
    RunNotFoundError,
    UnknownBuildTypeError,
)

OWNER = "founder-sub-abc"
OTHER = "someone-else"


def _service(core: FakeCoreGateway) -> IdeaScoutService:
    return IdeaScoutService(core, research_model="research-m", synthesis_model="synthesis-m")


async def _start(core: FakeCoreGateway, *, owner_sub: str = OWNER, complexity: int = 3):
    return await _service(core).start_run(
        owner_sub=owner_sub, build_type="micro-saas", complexity=complexity
    )


async def _run_to_completion(core: FakeCoreGateway, run_id: str, *, candidates: int = 5):
    """Drive a started run all the way to complete, the way polling would."""
    svc = _service(core)
    core.complete_all_research(run_id)
    await svc.get_run(owner_sub=OWNER, run_id=run_id)  # research -> synthesising
    core.synthesis_run_for(run_id).complete(candidates_message(candidates))
    return await svc.get_run(owner_sub=OWNER, run_id=run_id)  # synthesising -> complete


# ── Starting a run ───────────────────────────────────────────────────────────


async def test_start_fans_out_to_all_three_research_angles():
    core = FakeCoreGateway()
    run = await _start(core)

    assert run.status == m.RESEARCHING
    assert len(run.research_run_ids) == 3
    assert [r["agent_name"] for r in core.requested] == list(RESEARCH_AGENT_NAMES)


async def test_the_brief_carries_the_profile_the_build_type_and_the_complexity():
    core = FakeCoreGateway(
        profile=UserProfile(headline="Fractional CTO", focus_areas=["fintech"]),
        build_types=[
            BuildType(
                id="bt1",
                key="micro-saas",
                label="MicroSaaS",
                description="One narrow job, one buyer.",
                active=True,
            )
        ],
    )
    await _start(core, complexity=2)

    brief = core.requested[0]["input_payload"]["brief"]
    assert brief["build_type"]["label"] == "MicroSaaS"
    assert brief["build_type"]["description"] == "One narrow job, one buyer."
    assert brief["profile"]["headline"] == "Fractional CTO"
    assert brief["profile"]["focus_areas"] == ["fintech"]
    # The slider position is briefed in words — "2 out of 5" means nothing to a model.
    assert "small" in brief["complexity"]


async def test_an_empty_profile_is_omitted_from_the_brief_rather_than_sent_as_nulls():
    """Sending a shape full of nulls invites the model to invent a founder to
    fit it. The run still happens — just unpersonalised."""
    core = FakeCoreGateway(profile=UserProfile())
    run = await _start(core)

    assert "profile" not in core.requested[0]["input_payload"]["brief"]
    assert run.status == m.RESEARCHING


async def test_the_profile_is_snapshotted_on_the_run():
    """So the run stays explicable after the founder edits their profile."""
    core = FakeCoreGateway(profile=UserProfile(headline="Fractional CTO"))
    run = await _start(core)

    assert run.profile_snapshot is not None
    assert run.profile_snapshot["headline"] == "Fractional CTO"


def test_the_snapshot_omits_fields_that_tell_an_agent_nothing():
    from idea_scout.service import _profile_payload

    payload = _profile_payload(UserProfile(headline="x"))
    assert "linkedin_url" not in payload
    assert "updated_at" not in payload


async def test_research_agents_get_the_search_tool_and_the_findings_output_tool():
    core = FakeCoreGateway()
    await _start(core)

    for request in core.requested:
        assert request["definition"]["tools"] == ["web_search"]
        assert request["output_tool"]["function"]["name"] == "submit_research_findings"


async def test_an_inactive_build_type_is_rejected():
    """It arrives from a client, so it is validated against the *active* list —
    an admin who withdrew a category meant it."""
    core = FakeCoreGateway(
        build_types=[BuildType(id="bt1", key="micro-saas", label="MicroSaaS", active=False)]
    )
    with pytest.raises(UnknownBuildTypeError):
        await _start(core)


async def test_an_unknown_build_type_is_rejected():
    core = FakeCoreGateway()
    with pytest.raises(UnknownBuildTypeError):
        await _service(core).start_run(owner_sub=OWNER, build_type="invented", complexity=3)


@pytest.mark.parametrize("complexity", [0, 6, -1, 99])
async def test_complexity_outside_the_slider_is_rejected(complexity: int):
    core = FakeCoreGateway()
    with pytest.raises(InvalidComplexityError):
        await _start(core, complexity=complexity)


async def test_nothing_is_requested_when_validation_fails():
    """A rejected run must not leave paid-for agent runs behind."""
    core = FakeCoreGateway()
    with pytest.raises(InvalidComplexityError):
        await _start(core, complexity=99)
    assert core.requested == []
    assert core.runs == {}


# ── Research -> synthesis ────────────────────────────────────────────────────


async def test_the_run_stays_researching_while_any_angle_is_in_flight():
    core = FakeCoreGateway()
    run = await _start(core)

    core.research_runs_for(run.id)[0].complete(findings_message())
    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.RESEARCHING
    assert state.synthesis_run_id is None


async def test_synthesis_fires_once_every_angle_is_terminal():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.SYNTHESISING
    assert state.synthesis_run_id is not None
    assert core.requested[-1]["agent_name"] == SYNTHESIS_AGENT_NAME


async def test_the_synthesis_agent_receives_every_angles_findings():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    payload = core.requested[-1]["input_payload"]
    assert len(payload["findings"]) == 3
    assert payload["build_type"] == "micro-saas"
    assert payload["profile"] is not None


async def test_a_failed_angle_degrades_rather_than_failing_the_run():
    """Three angles are deliberately redundant."""
    core = FakeCoreGateway()
    run = await _start(core)
    research = core.research_runs_for(run.id)
    research[0].fail()
    research[1].complete(findings_message())
    research[2].complete(findings_message())

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.SYNTHESISING
    assert len(core.requested[-1]["input_payload"]["findings"]) == 2


async def test_an_angle_that_returns_no_tool_call_is_dropped():
    core = FakeCoreGateway()
    run = await _start(core)
    research = core.research_runs_for(run.id)
    research[0].complete([{"role": "assistant", "content": "I could not find anything."}])
    research[1].complete(findings_message())
    research[2].complete(findings_message())

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.SYNTHESISING
    assert len(core.requested[-1]["input_payload"]["findings"]) == 2


async def test_all_angles_failing_fails_the_run_with_a_readable_reason():
    core = FakeCoreGateway()
    run = await _start(core)
    for agent_run in core.research_runs_for(run.id):
        agent_run.fail()

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    assert state.failure_reason is not None
    assert "try running again" in state.failure_reason.lower()


async def test_an_agent_run_core_has_lost_counts_as_failed_not_pending():
    """Otherwise a vanished run leaves the scout waiting forever."""
    core = FakeCoreGateway()
    run = await _start(core)
    core.vanished_agent_runs = set(run.research_run_ids)

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED


# ── Synthesis -> complete ────────────────────────────────────────────────────


async def test_a_completed_synthesis_stores_ranked_candidates():
    core = FakeCoreGateway()
    run = await _start(core)
    state = await _run_to_completion(core, run.id)

    assert state.status == m.COMPLETE
    candidates = await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id)
    assert [c.rank for c in candidates] == [1, 2, 3, 4, 5]
    assert candidates[0].title == "Idea 1"
    assert candidates[0].scorecard is not None
    assert candidates[0].model == "test-model"


async def test_candidates_are_empty_while_the_run_is_in_flight():
    core = FakeCoreGateway()
    run = await _start(core)

    assert await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id) == []


async def test_polling_candidates_alone_still_advances_the_run():
    """The UI may poll only this endpoint; it must not deadlock the run."""
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)

    await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id)
    assert core.runs[run.id].status == m.SYNTHESISING

    core.synthesis_run_for(run.id).complete(candidates_message())
    candidates = await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id)
    assert len(candidates) == 5


async def test_an_over_long_shortlist_is_trimmed_not_rejected():
    """The model ignoring its brief is not a broken run, and the ranking means
    the extras are the ones it rated lowest."""
    core = FakeCoreGateway()
    run = await _start(core)
    await _run_to_completion(core, run.id, candidates=MAX_CANDIDATES + 4)

    candidates = await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id)
    assert len(candidates) == MAX_CANDIDATES


async def test_a_failed_synthesis_fails_the_run():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)
    core.synthesis_run_for(run.id).fail()

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    assert state.failure_reason is not None


async def test_a_synthesis_that_returns_nothing_usable_fails_the_run():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)
    core.synthesis_run_for(run.id).complete([{"role": "assistant", "content": "Here you go!"}])

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED


async def test_a_synthesis_returning_an_empty_list_fails_the_run():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)
    core.synthesis_run_for(run.id).complete(candidates_message(0))

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED


async def test_a_completed_run_is_not_re_synthesised_on_further_polls():
    """Every poll after completion must be a read — re-firing would bill the
    founder again for a shortlist they already have."""
    core = FakeCoreGateway()
    run = await _start(core)
    await _run_to_completion(core, run.id)
    requested_before = len(core.requested)
    stored_before = len(core.candidates)

    for _ in range(3):
        await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert len(core.requested) == requested_before
    assert len(core.candidates) == stored_before


async def test_a_failed_run_is_not_retried_on_further_polls():
    core = FakeCoreGateway()
    run = await _start(core)
    for agent_run in core.research_runs_for(run.id):
        agent_run.fail()
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)
    requested_before = len(core.requested)

    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert len(core.requested) == requested_before


# ── Admin-configured prompts ─────────────────────────────────────────────────


async def test_a_configured_prompt_and_model_override_the_built_in_default():
    core = FakeCoreGateway(
        configs={
            RESEARCH_AGENT_NAMES[0]: {
                "system_prompt": "A custom brief.",
                "model": "custom-model",
            }
        }
    )
    await _start(core)

    first = core.requested[0]["definition"]
    assert first["instructions"] == "A custom brief."
    assert first["model"] == "custom-model"
    # Unconfigured roles still get the built-in default and the module's model.
    assert core.requested[1]["definition"]["model"] == "research-m"


async def test_the_built_in_default_is_used_when_nothing_is_configured():
    core = FakeCoreGateway()
    await _start(core)

    from idea_scout.definitions import DEFAULT_INSTRUCTIONS

    assert (
        core.requested[0]["definition"]["instructions"]
        == DEFAULT_INSTRUCTIONS[RESEARCH_AGENT_NAMES[0]]
    )


# ── Listing, deleting, ownership ─────────────────────────────────────────────


async def test_runs_are_listed_most_recent_first():
    core = FakeCoreGateway()
    first = await _start(core)
    second = await _start(core)

    runs = await _service(core).list_runs(owner_sub=OWNER)

    assert [r.id for r in runs] == [second.id, first.id]


async def test_listing_does_not_advance_any_run():
    """The sidebar must not fan out reads across every run on every page load."""
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    requested_before = len(core.requested)

    await _service(core).list_runs(owner_sub=OWNER)

    assert len(core.requested) == requested_before
    assert core.runs[run.id].status == m.RESEARCHING


async def test_a_deleted_run_disappears_from_the_list_and_reads_as_missing():
    core = FakeCoreGateway()
    run = await _start(core)
    svc = _service(core)

    await svc.delete_run(owner_sub=OWNER, run_id=run.id)

    assert await svc.list_runs(owner_sub=OWNER) == []
    with pytest.raises(RunNotFoundError):
        await svc.get_run(owner_sub=OWNER, run_id=run.id)


async def test_an_in_flight_run_can_be_deleted():
    core = FakeCoreGateway()
    run = await _start(core)
    await _service(core).delete_run(owner_sub=OWNER, run_id=run.id)
    assert core.runs[run.id].deleted is True


async def test_another_founders_run_is_not_readable():
    core = FakeCoreGateway()
    run = await _start(core, owner_sub=OWNER)
    svc = _service(core)

    with pytest.raises(RunNotFoundError):
        await svc.get_run(owner_sub=OTHER, run_id=run.id)
    with pytest.raises(RunNotFoundError):
        await svc.delete_run(owner_sub=OTHER, run_id=run.id)
    assert await svc.list_runs(owner_sub=OTHER) == []


async def test_another_founders_candidates_are_not_readable():
    core = FakeCoreGateway()
    run = await _start(core, owner_sub=OWNER)
    await _run_to_completion(core, run.id)

    with pytest.raises(RunNotFoundError):
        await _service(core).get_candidates(owner_sub=OTHER, run_id=run.id)


async def test_a_missing_run_reads_as_not_found():
    core = FakeCoreGateway()
    with pytest.raises(RunNotFoundError):
        await _service(core).get_run(owner_sub=OWNER, run_id="nope")


# ── Extraction ───────────────────────────────────────────────────────────────


def test_a_retried_tool_call_uses_the_later_attempt():
    """If a model retries after a malformed call, the later one is what it meant."""
    from idea_scout.service import extract_candidates

    messages = candidates_message(1) + candidates_message(3)
    assert len(extract_candidates(messages).candidates) == 3


def test_unparseable_tool_arguments_are_skipped_rather_than_crashing():
    from idea_scout.service import extract_findings

    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "submit_research_findings", "arguments": "{not json"}}
            ],
        }
    ]
    assert extract_findings(messages) is None


def test_candidates_from_a_wrong_shaped_tool_call_are_rejected():
    from idea_scout.service import MalformedCandidatesError, extract_candidates

    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "submit_idea_candidates",
                        "arguments": '{"candidates": [{"title": "no pitch or scorecard"}]}',
                    }
                }
            ],
        }
    ]
    with pytest.raises(MalformedCandidatesError):
        extract_candidates(messages)


def test_a_candidate_payload_round_trips_through_the_schema():
    """Guards the fake against drifting from the real schema — a fake that
    produces data the model would reject makes every test above meaningless."""
    from idea_scout.definitions import Candidate as CandidateModel

    assert CandidateModel.model_validate(candidate_payload("x")).title == "x"
