"""Tests for the log-only novelty score (#49, option C).

Two layers:

- Pure tests of ``novelty.score_novelty`` — including the load-bearing one,
  which reproduces the operator's own by-eye labelling of a real four-run
  comparison recorded on #49 (2026-07-29 comment). The owner's memo is explicit
  that if the judge cannot reproduce those labels, option C should be
  abandoned rather than tuned — so this is the test that decides whether the
  rest of this file's design is sound at all.
- Service-level tests: the score is computed and logged for every run, only
  the requesting founder's own prior candidates reach it, a failure to compute
  it cannot fail the run it is about, and the candidates a founder is actually
  shown are byte-for-byte unaffected by any of this.
"""

from __future__ import annotations

import json
import logging

from fakes import FakeCoreGateway, candidate_payload
from test_idea_scout_service import _BUILD_TYPE, OTHER, OWNER, _past_run, _seed_core, _service

from idea_scout import models as m
from idea_scout.models import Candidate
from idea_scout.novelty import score_novelty

# ── Pure scoring tests ───────────────────────────────────────────────────────


def test_a_founders_first_run_has_nothing_to_repeat_so_everything_is_novel():
    result = score_novelty(
        candidates=[{"title": "Anything at all", "pitch": "Some pitch."}],
        prior=[],
    )
    assert result.novelty_score == 1.0
    assert result.candidates[0].is_novel is True
    assert result.candidates[0].closest_prior_title is None


def test_an_identical_title_and_pitch_is_never_judged_novel():
    result = score_novelty(
        candidates=[{"title": "AgentCost", "pitch": "Bedrock spend dashboard."}],
        prior=[{"title": "AgentCost", "pitch": "Bedrock spend dashboard."}],
    )
    assert result.candidates[0].is_novel is False
    assert result.candidates[0].closest_prior_title == "AgentCost"
    assert result.novelty_score == 0.0


def test_reproduces_the_operators_own_labels():
    """The load-bearing acceptance test named in #49's decision.

    Fixture is exactly the titles/pitches recorded in the 2026-07-29 comment
    (https://github.com/keiranholloway/biffo-plugin-idea-scout/issues/49):
    three pre-fix runs' candidates (the "prior candidate it reproduces" column,
    read as ``title — pitch`` where the comment used that separator, title-only
    where it did not) as the founder's history, and the one post-fix run's four
    candidates as what is being scored. The operator judged three of the four
    thematic near-duplicates and one ("MV3 Rescue") genuinely new — roughly
    25% novelty, stated explicitly in that comment.

    If this fails, the PR body says so plainly and does NOT tune the threshold
    to force agreement — an honest disagreement is the valid outcome here.
    """
    prior = [
        {"title": "AgentCost", "pitch": "Bedrock token spend & cost-attribution dashboard"},
        {"title": "BedrockGuard", "pitch": ""},
        {"title": "Compliance-Evidence Autopilot for Fintechs on AWS/GCP", "pitch": ""},
        {"title": "Cloud Cost & Config Drift Watchdog", "pitch": ""},
    ]
    candidates = [
        {
            "title": "BedrockBudget",
            "pitch": "predictive cost & spend-cap guardrail for AWS AI/ML workloads",
        },
        {
            "title": "MV3 Rescue",
            "pitch": "drop-in replacements for extensions that went dark",
        },
        {
            "title": "PCI Autopilot",
            "pitch": "continuous compliance evidence for fintech teams on AWS",
        },
        {
            "title": "AI-Spend Anomaly Alerts",
            "pitch": "Bedrock/LLM token-cost watchdog",
        },
    ]
    operators_labels = {
        "BedrockBudget": False,  # near-duplicate of AgentCost / BedrockGuard
        "MV3 Rescue": True,  # "— genuinely new"
        "PCI Autopilot": False,  # near-duplicate of Compliance-Evidence Autopilot...
        "AI-Spend Anomaly Alerts": False,  # near-duplicate of AgentCost / ...Watchdog
    }

    result = score_novelty(candidates=candidates, prior=prior)

    scored_labels = {c.title: c.is_novel for c in result.candidates}
    assert scored_labels == operators_labels, (
        f"novelty judge disagrees with the operator's own labelling: "
        f"scored={scored_labels} operator={operators_labels} "
        f"(similarities={[(c.title, c.similarity) for c in result.candidates]})"
    )
    # "roughly 25 percent novelty" — one genuinely new idea in four.
    assert result.novelty_score == 0.25


def test_agrees_with_the_held_out_titles_and_pitches_run():
    """Genuine held-out validation (biffo-fleet prosecutor issue #134).

    ``test_reproduces_the_operators_own_labels`` above is circular by
    construction: ``NOVELTY_SIMILARITY_THRESHOLD`` was read directly off the
    similarities that fixture produces (see the constant's own comment in
    ``novelty.py``), so that test cannot fail for any threshold in the gap
    those four points happen to leave. It is not evidence the judge
    generalises to a point it was not fitted against.

    This test supplies one: the operator's titles+pitches experiment (PR #58
    / biffo-platform#118, referenced from #49's 2026-07-29 comment), run
    *after* the four-candidate fixture above and never used to pick 0.10.
    That run returned 2 candidates, both judged near-duplicate by the
    operator, one an explicitly verbatim reuse of the prior "BedrockBudget"
    product name with a reworded pitch:

        "the names also got closer, not further apart:
        `BedrockBudget — predictive cost & spend-cap guardrail for AWS
        AI/ML workloads` -> `BedrockBudget — predictive spend-cap guardrail
        for small teams' AWS AI/ML workloads` ... the same product name,
        reused verbatim"

    The second of that run's two candidates is not used here: its exact
    title and pitch were never recorded anywhere retrievable in #49's
    thread or its linked PRs, only the aggregate count (2 candidates, 2
    near-duplicates). Inventing text for it would defeat the point of a
    held-out check, so this holds out only the one point the record
    actually contains — issue #134's suggested resolution (b) asks for "at
    least one".

    ``prior`` here is the founder's actual accumulated history at the time
    of this run: the four-candidate fixture's own prior *plus* that
    fixture's four scored candidates, because the titles+pitches run
    happened after the titles-only run those candidates came from — a
    founder's own prior output becomes history for their next run, exactly
    as ``_previously_suggested`` (#49's real mechanism) reads it.

    If this disagreed with the operator's label, the fix would be to say so
    and stop — not to move the threshold or the fixture to force agreement.
    It agrees.
    """
    prior = [
        {"title": "AgentCost", "pitch": "Bedrock token spend & cost-attribution dashboard"},
        {"title": "BedrockGuard", "pitch": ""},
        {"title": "Compliance-Evidence Autopilot for Fintechs on AWS/GCP", "pitch": ""},
        {"title": "Cloud Cost & Config Drift Watchdog", "pitch": ""},
        # The titles-only run's own four candidates, scored above, which by
        # the time of the titles+pitches run are also this founder's history.
        {
            "title": "BedrockBudget",
            "pitch": "predictive cost & spend-cap guardrail for AWS AI/ML workloads",
        },
        {
            "title": "MV3 Rescue",
            "pitch": "drop-in replacements for extensions that went dark",
        },
        {
            "title": "PCI Autopilot",
            "pitch": "continuous compliance evidence for fintech teams on AWS",
        },
        {
            "title": "AI-Spend Anomaly Alerts",
            "pitch": "Bedrock/LLM token-cost watchdog",
        },
    ]
    held_out_candidate = {
        "title": "BedrockBudget",
        "pitch": "predictive spend-cap guardrail for small teams' AWS AI/ML workloads",
    }

    result = score_novelty(candidates=[held_out_candidate], prior=prior)

    assert result.candidates[0].is_novel is False, (
        "held-out point disagrees with the operator's own label (near-duplicate): "
        f"similarity={result.candidates[0].similarity} "
        f"closest={result.candidates[0].closest_prior_title}"
    )
    assert result.candidates[0].closest_prior_title == "BedrockBudget"


# ── Service-level tests ──────────────────────────────────────────────────────


def _synthesis_message(pairs: list[tuple[str, str]]) -> list[dict[str, object]]:
    """A synthesis transcript carrying candidates with specific title/pitch
    pairs, rather than the generic ``candidates_message`` helper's generated
    ones — needed to drive scoring with known text."""
    candidates = []
    for title, pitch in pairs:
        payload = candidate_payload(title)
        payload["pitch"] = pitch
        candidates.append(payload)
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "submit_idea_candidates",
                        "arguments": json.dumps({"candidates": candidates}),
                    }
                }
            ],
        }
    ]


async def _start(core: FakeCoreGateway, *, owner_sub: str = OWNER):
    _seed_core(core)
    return await _service(core).start_run(
        owner_sub=owner_sub, build_type="micro-saas", complexity=3
    )


async def _complete_with(core: FakeCoreGateway, run_id: str, pairs: list[tuple[str, str]]):
    svc = _service(core)
    core.complete_all_research(run_id)
    synthesis = core.engine_fires_synthesis(run_id)
    await svc.get_run(owner_sub=OWNER, run_id=run_id)
    synthesis.complete(_synthesis_message(pairs))
    return await svc.get_run(owner_sub=OWNER, run_id=run_id)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _capture_service_logs():
    """Capture from the module's own logger, matching app.py/admin_app.py's
    tests — propagation to the root handler is not guaranteed once this file
    is vendored into biffo-platform (see test_idea_scout_app.py)."""
    from idea_scout import service as service_module

    handler = _Capture()
    service_module._LOGGER.addHandler(handler)
    previous_level = service_module._LOGGER.level
    service_module._LOGGER.setLevel(logging.INFO)
    return service_module, handler, previous_level


async def test_novelty_is_logged_for_every_completed_run():
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    run = await _start(core)
    service_module, handler, previous_level = _capture_service_logs()
    try:
        state = await _complete_with(core, run.id, [("Some idea", "A pitch nobody has seen.")])
    finally:
        service_module._LOGGER.removeHandler(handler)
        service_module._LOGGER.setLevel(previous_level)

    assert state.status == m.COMPLETE
    novelty_logs = [r for r in handler.records if "Novelty for run" in r.getMessage()]
    assert len(novelty_logs) == 1
    assert run.id in novelty_logs[0].getMessage()
    assert "score=1.00" in novelty_logs[0].getMessage()  # first run: nothing to repeat


async def test_only_the_requesting_founders_prior_candidates_reach_the_score():
    """Owner-scoping test — this reads across runs, like ``_previously_suggested``
    (#49's original mechanism) already must and does.

    If this leaked another founder's candidates into the comparison pool, a
    fresh candidate that happens to share a title with a stranger's prior idea
    would wrongly score as a repeat. It must not: OTHER's identical-titled
    candidate must be invisible to OWNER's run.
    """
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    _past_run(core, "theirs", OTHER, created_at="2026-07-01T00:00:00Z")
    core.candidates.append(
        Candidate(
            id="c1",
            run_id="theirs",
            rank=1,
            title="Exact Same Title",
            pitch="Exact same pitch text too.",
        )
    )
    run = await _start(core, owner_sub=OWNER)

    service_module, handler, previous_level = _capture_service_logs()
    try:
        await _complete_with(core, run.id, [("Exact Same Title", "Exact same pitch text too.")])
    finally:
        service_module._LOGGER.removeHandler(handler)
        service_module._LOGGER.setLevel(previous_level)

    novelty_logs = [r for r in handler.records if "Novelty for run" in r.getMessage()]
    assert len(novelty_logs) == 1
    # OTHER's identically-titled candidate must not have reached the score:
    # OWNER has no history of their own, so this must read as fully novel.
    assert "score=1.00" in novelty_logs[0].getMessage()


async def test_candidates_shown_to_the_founder_are_unchanged_in_count_and_content():
    """Level-4 detect-only: scoring must never filter, reorder, or alter a
    candidate. Seed a founder with prior candidates that are near-duplicates
    of what this run will return, so a wrongly-built filter would show up as
    a shrunk list."""
    core = FakeCoreGateway(build_types=[_BUILD_TYPE])
    _past_run(core, "prior", OWNER, created_at="2026-07-01T00:00:00Z")
    core.candidates.append(
        Candidate(
            id="c1",
            run_id="prior",
            rank=1,
            title="AgentCost",
            pitch="Bedrock token spend & cost-attribution dashboard",
        )
    )
    run = await _start(core)

    pairs = [
        ("BedrockBudget", "predictive cost & spend-cap guardrail for AWS AI/ML workloads"),
        ("MV3 Rescue", "drop-in replacements for extensions that went dark"),
    ]
    await _complete_with(core, run.id, pairs)

    candidates = await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id)
    assert [(c.title, c.pitch) for c in candidates] == pairs
    assert len(candidates) == 2


async def test_a_failure_scoring_novelty_does_not_fail_the_run():
    """A measurement is strictly secondary to the run it describes (#49,
    option C is explicitly log-only) — if the owner-scoped read that feeds it
    errors, the founder must still get their candidates."""

    class _ExplodingOnOwnerCandidates(FakeCoreGateway):
        """Succeeds on ``start_run``'s own ``_previously_suggested`` read (#49's
        existing mechanism, unaffected by this change) and fails only on the
        later read this run's own novelty scoring makes."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self._owner_candidate_calls = 0

        async def list_owner_candidates(self, *, owner_sub: str) -> list[Candidate]:
            self._owner_candidate_calls += 1
            if self._owner_candidate_calls > 1:
                raise RuntimeError("Core is unavailable")
            return await super().list_owner_candidates(owner_sub=owner_sub)

    core = _ExplodingOnOwnerCandidates(build_types=[_BUILD_TYPE])
    run = await _start(core)

    service_module, handler, previous_level = _capture_service_logs()
    try:
        state = await _complete_with(core, run.id, [("Some idea", "A pitch.")])
    finally:
        service_module._LOGGER.removeHandler(handler)
        service_module._LOGGER.setLevel(previous_level)

    assert state.status == m.COMPLETE
    candidates = await _service(core).get_candidates(owner_sub=OWNER, run_id=run.id)
    assert len(candidates) == 1
    assert any(r.levelno == logging.ERROR for r in handler.records), (
        "the scoring failure should be logged even though it must not fail the run"
    )
