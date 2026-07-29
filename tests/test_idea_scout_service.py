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
    MAX_PREVIOUSLY_SUGGESTED,
    RESEARCH_AGENT_NAMES,
)
from idea_scout.models import BuildType, Candidate, ScoutRun, UserProfile
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
    """Drive a started run to complete.

    Note what the *plugin* does here versus what the **engine** does: the engine
    fires the synthesis run when the research set finishes, and the plugin only
    discovers it. `engine_fires_synthesis` stands in for that.
    """
    svc = _service(core)
    core.complete_all_research(run_id)
    synthesis = core.engine_fires_synthesis(run_id)
    await svc.get_run(owner_sub=OWNER, run_id=run_id)  # picks up the engine's run
    synthesis.complete(candidates_message(candidates))
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


_BUILD_TYPE = BuildType(
    id="bt1", key="micro-saas", label="MicroSaaS", description="One narrow job.", active=True
)


def _past_run(core: FakeCoreGateway, run_id: str, owner_sub: str, *, created_at: str) -> None:
    """A finished run of someone's, so its candidates are reachable and owned.

    Ownership of a candidate is reached through its run — that is what the real
    owner-data route enforces via the forwarded token, and what the fake mirrors.
    """
    core.runs[run_id] = ScoutRun(
        id=run_id,
        owner_sub=owner_sub,
        build_type="micro-saas",
        complexity=3,
        chain_id=f"chain-{run_id}",
        status="complete",
        created_at=created_at,
    )


async def test_the_brief_carries_titles_the_founder_has_already_been_shown():
    """A founder running twice must not be shown the same ideas twice (#49).

    The history was always in `idea_scout_candidates` and never read back, so
    nothing told the agents which ground was already covered.
    """
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    _past_run(core, "r1", OWNER, created_at="2026-07-01T00:00:00Z")
    core.candidates += [
        Candidate(id="c1", run_id="r1", rank=1, title="Invoice chaser for clinics", pitch="p"),
        Candidate(id="c2", run_id="r1", rank=2, title="Rota planner for locums", pitch="p"),
    ]

    await _start(core)

    brief = core.requested[0]["input_payload"]["brief"]
    assert "Invoice chaser for clinics" in brief["previously_suggested"]
    assert "Rota planner for locums" in brief["previously_suggested"]


async def test_the_previously_suggested_key_is_omitted_when_there_is_no_history():
    """Same reason an empty profile is omitted: an empty list invites the model
    to reason about a set that does not exist."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])

    await _start(core)

    assert "previously_suggested" not in core.requested[0]["input_payload"]["brief"]


async def test_only_the_requesting_founders_own_titles_reach_the_brief():
    """The first read that crosses runs, so owner scoping is asserted rather
    than assumed from the transport."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    _past_run(core, "mine", OWNER, created_at="2026-07-01T00:00:00Z")
    _past_run(core, "theirs", OTHER, created_at="2026-07-02T00:00:00Z")
    core.candidates += [
        Candidate(id="c1", run_id="mine", rank=1, title="Mine", pitch="p"),
        Candidate(id="c2", run_id="theirs", rank=1, title="Theirs", pitch="p"),
    ]

    await _start(core)

    suggested = core.requested[0]["input_payload"]["brief"]["previously_suggested"]
    assert "Mine" in suggested
    assert "Theirs" not in suggested


async def test_the_history_is_capped_and_keeps_the_most_recent():
    """An unbounded history eventually dominates the prompt."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    _past_run(core, "old", OWNER, created_at="2026-07-01T00:00:00Z")
    _past_run(core, "new", OWNER, created_at="2026-07-09T00:00:00Z")
    core.candidates += [
        Candidate(id=f"o{i}", run_id="old", rank=i, title=f"Old idea {i}", pitch="p")
        for i in range(MAX_PREVIOUSLY_SUGGESTED)
    ]
    core.candidates += [Candidate(id="n1", run_id="new", rank=1, title="Newest idea", pitch="p")]

    await _start(core)

    suggested = core.requested[0]["input_payload"]["brief"]["previously_suggested"]
    assert len(suggested) == MAX_PREVIOUSLY_SUGGESTED
    assert "Newest idea" in suggested, "the cap dropped the most recent instead of the oldest"


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


async def test_research_agents_get_no_registry_tool_and_the_findings_output_tool():
    """Search rides on the ``:online`` model, so the run declares no registry
    tool — a declared-but-unconfigured one is silently dropped, which is how the
    first real run produced nothing."""
    core = FakeCoreGateway()
    await _start(core)

    for request in core.requested:
        assert request["definition"]["tools"] == []
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


async def test_the_run_waits_while_the_engine_has_not_fired_synthesis():
    """Research all terminal, but the engine has not reacted yet. The plugin must
    not race it to a false failure — nor fire synthesis itself."""
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.RESEARCHING
    # Three research runs and nothing else: the plugin did not fire synthesis.
    assert [r["agent_name"] for r in core.requested] == list(RESEARCH_AGENT_NAMES)


async def test_the_run_picks_up_the_synthesis_run_the_engine_fired():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    synthesis = core.engine_fires_synthesis(run.id)

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.SYNTHESISING
    assert state.synthesis_run_id == synthesis.id


async def test_the_three_research_runs_share_one_chain():
    """The whole fan-in depends on this: uncorrelated runs are three chain roots
    and the engine's join would never recognise them as a set."""
    core = FakeCoreGateway()
    run = await _start(core)

    chains = {r["causation_id"] for r in core.requested}
    assert len(chains) == 1
    assert chains == {run.chain_id}


async def test_two_concurrent_scouts_do_not_share_a_chain():
    """Otherwise one founder's research would satisfy another's join."""
    core = FakeCoreGateway()
    first = await _start(core)
    second = await _start(core)

    assert first.chain_id != second.chain_id


async def test_a_failed_angle_does_not_fail_the_run_while_others_succeeded():
    """Degrading past a dead angle is the engine's call now, but the plugin must
    not pre-empt it by failing the run."""
    core = FakeCoreGateway()
    run = await _start(core)
    research = core.research_runs_for(run.id)
    research[0].fail()
    research[1].complete(findings_message())
    research[2].complete(findings_message())

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.RESEARCHING  # waiting on the engine, not failed


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
    synthesis = core.engine_fires_synthesis(run.id)

    await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id)
    assert core.runs[run.id].status == m.SYNTHESISING

    synthesis.complete(candidates_message())
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
    synthesis = core.engine_fires_synthesis(run.id)
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)
    synthesis.fail()

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    assert state.failure_reason is not None


async def test_a_synthesis_that_returns_nothing_usable_fails_the_run():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    synthesis = core.engine_fires_synthesis(run.id)
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)
    synthesis.complete([{"role": "assistant", "content": "Here you go!"}])

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED


async def test_a_synthesis_returning_an_empty_list_fails_the_run():
    core = FakeCoreGateway()
    run = await _start(core)
    core.complete_all_research(run.id)
    synthesis = core.engine_fires_synthesis(run.id)
    await _service(core).get_run(owner_sub=OWNER, run_id=run.id)
    synthesis.complete(candidates_message(0))

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


# ── Honest failure copy: never-started vs actually-failed (#27) ──────────────
#
# Core's reaper fails a run nothing ever claimed (biffo-template#786). Before
# this, the founder was told "the analysis finished but returned nothing usable"
# or "the analysis failed" — both of which say it RAN. It never did. That sends
# the reader (and us) to look at the model or the prompt instead of at event
# delivery, which is where the fault actually is (biffo-platform#96).


async def test_a_synthesis_run_that_never_started_says_so():
    core = FakeCoreGateway()
    svc = _service(core)
    run = await _start(core)
    core.complete_all_research(run.id)
    synthesis = core.engine_fires_synthesis(run.id)
    # One poll picks up the engine's run (researching -> synthesising); the next
    # evaluates it. Same two-step the real UI does, per `_run_to_completion`.
    await svc.get_run(owner_sub=OWNER, run_id=run.id)
    synthesis.never_claimed()

    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    reason = state.failure_reason or ""
    assert "never started" in reason.lower()
    # The specific wrong claim this replaces.
    assert "analysis" not in reason.lower(), reason


async def test_research_runs_that_never_started_say_so():
    """Same delivery fault, one stage earlier."""
    core = FakeCoreGateway()
    run = await _start(core)
    for agent_run in core.research_runs_for(run.id):
        agent_run.never_claimed()

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    assert "never started" in (state.failure_reason or "").lower()


async def test_a_run_that_actually_ran_and_failed_still_says_that():
    """Guards the guard. If `never_started` were true for every failure, the
    two tests above would pass while the honest distinction was lost."""
    core = FakeCoreGateway()
    run = await _start(core)
    for agent_run in core.research_runs_for(run.id):
        agent_run.fail()  # claimed, ran, errored — started_at IS set

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    reason = (state.failure_reason or "").lower()
    assert "never started" not in reason
    assert "failed to return usable findings" in reason


async def test_the_never_started_message_tells_the_founder_it_cost_nothing():
    """A founder who thinks they have been charged for a failed run behaves
    differently from one who knows they have not. Nothing was spent: the runs
    were never claimed, so no model was ever called."""
    core = FakeCoreGateway()
    run = await _start(core)
    for agent_run in core.research_runs_for(run.id):
        agent_run.never_claimed()

    state = await _service(core).get_run(owner_sub=OWNER, run_id=run.id)

    assert "nothing was charged" in (state.failure_reason or "").lower()


# ── Model catalog (M1) ───────────────────────────────────────────────────────


_MODEL_CATALOG = [
    m.ModelCatalogEntry(
        id="m1",
        model_id="openai/gpt-4:online",
        label="GPT-4",
        active=True,
        is_default=True,
        web_capable=True,
    ),
    m.ModelCatalogEntry(
        id="m2",
        model_id="anthropic/claude-opus:online",
        label="Claude Opus",
        active=True,
        is_default=False,
        web_capable=True,
    ),
    m.ModelCatalogEntry(
        id="m3",
        model_id="anthropic/claude-sonnet",
        label="Claude Sonnet",
        active=True,
        is_default=False,
        web_capable=False,
    ),
    m.ModelCatalogEntry(
        id="m4",
        model_id="anthropic/claude-haiku:online",
        label="Claude Haiku",
        active=False,
        is_default=False,
        web_capable=True,
    ),
]


async def test_a_model_without_web_capability_is_rejected():
    """Research agents need OpenRouter's :online suffix for web search capability.
    A model marked not web_capable cannot be used for research."""
    from idea_scout.service import UnknownModelError

    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG

    with pytest.raises(UnknownModelError):
        await _service(core).start_run(
            owner_sub=OWNER,
            build_type="micro-saas",
            complexity=3,
            research_model="m3",  # web_capable=False
        )


async def test_an_inactive_model_is_rejected():
    """Admin withdrew an inactive model; it should not be usable."""
    from idea_scout.service import UnknownModelError

    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG

    with pytest.raises(UnknownModelError):
        await _service(core).start_run(
            owner_sub=OWNER,
            build_type="micro-saas",
            complexity=3,
            research_model="m4",  # active=False
        )


async def test_an_unknown_model_is_rejected():
    """A model id not in the catalog cannot be used."""
    from idea_scout.service import UnknownModelError

    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG

    with pytest.raises(UnknownModelError):
        await _service(core).start_run(
            owner_sub=OWNER,
            build_type="micro-saas",
            complexity=3,
            research_model="invented-model",
        )


async def test_founders_chosen_model_beats_the_admin_row():
    """When a founder specifies research_model, it overrides the admin config."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG
    core.configs = {"idea-scout-community": {"system_prompt": "...", "model": "admin-model"}}

    await _service(core).start_run(
        owner_sub=OWNER,
        build_type="micro-saas",
        complexity=3,
        research_model="m1",
    )

    # Check that the requested agent runs use the founder's chosen model
    for request in core.requested:
        if request["agent_name"] in RESEARCH_AGENT_NAMES:
            assert request["definition"]["model"] == "openai/gpt-4:online"


async def test_admin_row_model_beats_builtin_default():
    """When no founder choice, but admin config exists, use the admin model."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG
    # Set admin config for all three research agents
    core.configs = {
        "idea-scout-community": {"system_prompt": "...", "model": "admin-model"},
        "idea-scout-narrative": {"system_prompt": "...", "model": "admin-model"},
        "idea-scout-competitive": {"system_prompt": "...", "model": "admin-model"},
    }

    await _service(core).start_run(
        owner_sub=OWNER,
        build_type="micro-saas",
        complexity=3,
    )

    # Check that the requested agent runs use the admin model
    for request in core.requested:
        if request["agent_name"] in RESEARCH_AGENT_NAMES:
            assert request["definition"]["model"] == "admin-model"


async def test_builtin_default_used_when_neither_founder_choice_nor_admin_row():
    """When no founder choice and no admin config, use the service default."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG

    await _service(core).start_run(
        owner_sub=OWNER,
        build_type="micro-saas",
        complexity=3,
    )

    # Check that the requested agent runs use the service's default research model
    for request in core.requested:
        if request["agent_name"] in RESEARCH_AGENT_NAMES:
            assert request["definition"]["model"] == "research-m"


async def test_research_model_is_recorded_on_the_run():
    """The chosen research_model's slug is stored so it can be displayed to the founder."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG

    run = await _service(core).start_run(
        owner_sub=OWNER,
        build_type="micro-saas",
        complexity=3,
        research_model="m2",
    )

    # run.research_model should be the resolved model_id slug, not the catalog entry id
    assert run.research_model == "anthropic/claude-opus:online"


async def test_research_model_none_when_not_specified():
    """When founder doesn't choose a model, research_model is None."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG

    run = await _service(core).start_run(
        owner_sub=OWNER,
        build_type="micro-saas",
        complexity=3,
    )

    assert run.research_model is None


async def test_founder_choice_reaches_all_three_research_agents_but_not_synthesis():
    """The founder's model choice affects ONLY the research agents, not synthesis."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    core.model_catalog = _MODEL_CATALOG

    await _service(core).start_run(
        owner_sub=OWNER,
        build_type="micro-saas",
        complexity=3,
        research_model="m1",
    )

    research_requests = [r for r in core.requested if r["agent_name"] in RESEARCH_AGENT_NAMES]
    synthesis_requests = [r for r in core.requested if r["agent_name"] == "idea-scout-synthesis"]

    # All three research agents get the founder's model
    assert len(research_requests) == 3
    for req in research_requests:
        assert req["definition"]["model"] == "openai/gpt-4:online"

    # Synthesis still gets the built-in/admin default, NOT the founder's choice
    assert len(synthesis_requests) == 0  # Synthesis is fired by the engine, not here
