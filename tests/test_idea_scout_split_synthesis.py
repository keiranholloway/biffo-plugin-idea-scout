"""Synthesis no longer writes the whole candidate set in one model call.

A ranking call scores and orders the shortlist; one write-up call per idea runs
in parallel. These tests pin the per-call output bound, the end-to-end fan-in at
a realistic input size, and the failure of a single write-up.
"""

from __future__ import annotations

import json
from typing import Any

from fakes import FakeCoreGateway, findings_message

from idea_scout import models as m
from idea_scout.definitions import (
    CANDIDATE_WRITER_AGENT_NAME,
    CANDIDATE_WRITER_INSTRUCTIONS,
    CANDIDATES_TOOL_NAME,
    MAX_CALL_OUTPUT_TOKENS,
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    SYNTHESIS_INSTRUCTIONS,
    WRITEUP_TOOL_NAME,
    candidates_tool_schema,
    seed_config_payloads,
    writeup_tool_schema,
)
from idea_scout.service import IdeaScoutService

OWNER = "founder-sub-abc"
#: Deliberately pessimistic: real English averages ~4 chars/token, JSON with
#: short keys and URLs is denser.
CHARS_PER_TOKEN = 3


def _worst_case_chars(node: Any, defs: dict[str, Any]) -> int:
    """Longest JSON a schema permits, in characters, from its maxLength/maxItems
    caps. An unbounded string or array raises: it has no bound to check."""
    if "$ref" in node:
        return _worst_case_chars(defs[node["$ref"].split("/")[-1]], defs)
    if "anyOf" in node:
        return max(_worst_case_chars(n, defs) for n in node["anyOf"])
    kind = node.get("type")
    if kind == "null":
        return 4
    if kind == "integer":
        return 2
    if kind == "string":
        assert "maxLength" in node, f"unbounded string in schema: {node}"
        return node["maxLength"] + 2
    if kind == "array":
        assert "maxItems" in node, f"unbounded array in schema: {node}"
        return node["maxItems"] * (_worst_case_chars(node["items"], defs) + 1) + 2
    assert kind == "object", node
    total = 2
    for key, sub in node["properties"].items():
        total += len(key) + 4 + _worst_case_chars(sub, defs)
    return total


def _worst_case_tokens(tool: dict[str, Any]) -> int:
    params = tool["function"]["parameters"]
    return _worst_case_chars(params, params.get("$defs", {})) // CHARS_PER_TOKEN + 1


def test_the_ranking_call_cannot_exceed_the_output_bound():
    assert _worst_case_tokens(candidates_tool_schema()) <= MAX_CALL_OUTPUT_TOKENS
    assert MAX_CALL_OUTPUT_TOKENS <= 4000


def test_a_write_up_call_cannot_exceed_the_output_bound():
    assert _worst_case_tokens(writeup_tool_schema()) <= MAX_CALL_OUTPUT_TOKENS


def test_the_prompts_name_the_one_tool_each_call_returns_through():
    assert CANDIDATES_TOOL_NAME in SYNTHESIS_INSTRUCTIONS
    assert WRITEUP_TOOL_NAME in CANDIDATE_WRITER_INSTRUCTIONS
    # Synthesis must not be asked for the per-candidate prose any more.
    assert "do not\n   write them here" in SYNTHESIS_INSTRUCTIONS


# ── The full fan-in ──────────────────────────────────────────────────────────


def _service(core: FakeCoreGateway) -> IdeaScoutService:
    for row in seed_config_payloads(research_model="research-m", synthesis_model="synthesis-m"):
        core.configs.setdefault(
            row["role"], {"system_prompt": row["system_prompt"], "model": row["model"]}
        )
    return IdeaScoutService(core)


def _call(tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": tool, "arguments": json.dumps(args)}}],
        }
    ]


def _ranking(count: int) -> list[dict[str, Any]]:
    # Deliberately NOT sorted by score: order is the ranking call's decision.
    ideas = [
        {
            "title": f"Idea {i + 1}",
            "pitch": f"Idea {i + 1} for someone, doing something, because now.",
            "viability": 5 - (i % 3),
            "complexity": 3,
            "economic_moat": 2,
            "market_fit": 4,
        }
        for i in range(count)
    ]
    return _call(CANDIDATES_TOOL_NAME, {"ideas": ideas})


def _writeup(label: str) -> list[dict[str, Any]]:
    axis = {"score": 1, "rationale": f"{label} rationale grounded in findings."}
    return _call(
        WRITEUP_TOOL_NAME,
        {
            "scorecard": {
                "viability": axis,
                "complexity": axis,
                "economic_moat": axis,
                "market_fit": axis,
                "build_vs_buy": "Build.",
                "competitors": [{"name": "Rival", "note": "Slow."}],
                "summary": f"{label} is worth a look.",
            },
            "sources": [{"url": "https://example.com/a", "note": "A thread."}],
        },
    )


def _big_findings(angle: str) -> list[dict[str, Any]]:
    """About 6,000 tokens of findings per angle — ~18,000 across the three, the
    size of the 2026-10-07 dev runs."""
    findings = [
        {
            "signal": f"{angle} signal {i}: " + "lorem ipsum dolor sit amet " * 20,
            "why_it_matters": "People are working around it manually. " * 8,
            "sources": [{"url": f"https://example.com/{angle}/{i}", "note": "A thread."}],
        }
        for i in range(18)
    ]
    return _call("submit_research_findings", {"angle": angle, "findings": findings})


async def _to_writeups(core: FakeCoreGateway, count: int):
    svc = _service(core)
    run = await svc.start_run(owner_sub=OWNER, build_type="micro-saas", complexity=3)
    for rid, angle in zip(
        run.research_run_ids, ("community", "narrative", "competitive"), strict=True
    ):
        core.agent_runs[rid].complete(_big_findings(angle))
    ranking = core.engine_fires_synthesis(run.id)
    ranking.complete(_ranking(count))
    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)  # -> synthesising
    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)  # fans out write-ups
    return svc, run, state


def _writer_runs(core: FakeCoreGateway):
    return [r for r in core.agent_runs.values() if r.agent_name == CANDIDATE_WRITER_AGENT_NAME]


async def test_a_full_fan_in_at_realistic_input_size_yields_ranked_scored_candidates():
    core = FakeCoreGateway()
    svc, run, state = await _to_writeups(core, 8)

    assert state.status == m.SYNTHESISING
    writers = _writer_runs(core)
    assert len(writers) == 8
    # Parallel: all requested before any has completed, each in its own chain,
    # none in the scout's chain (which would re-fire the engine's fan-in).
    assert len({w.causation_id for w in writers}) == 8
    assert run.chain_id not in {w.causation_id for w in writers}
    payload_chars = len(json.dumps(core.requested[-1]["input_payload"]))
    assert payload_chars > 40_000  # the findings really travelled

    for w in writers:
        w.complete(_writeup(w.id))
    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)
    assert state.status == m.COMPLETE
    assert state.failure_reason is None

    stored = await svc.get_candidates(owner_sub=OWNER, run_id=run.id)
    assert MIN_CANDIDATES <= len(stored) <= MAX_CANDIDATES
    assert [c.rank for c in stored] == list(range(1, 9))
    assert [c.title for c in stored] == [f"Idea {i}" for i in range(1, 9)]
    # Scores are the ranking call's, not whatever the write-up echoed.
    cards = [c.scorecard for c in stored]
    sc0: Any = cards[0]
    sc1: Any = cards[1]
    assert sc0["viability"]["score"] == 5
    assert sc1["viability"]["score"] == 4
    assert sc0["market_fit"]["score"] == 4
    assert sc0["summary"].endswith("is worth a look.")


async def test_the_ranking_is_not_complete_until_every_write_up_is_terminal():
    core = FakeCoreGateway()
    svc, run, _ = await _to_writeups(core, 5)
    writers = _writer_runs(core)
    for w in writers[:-1]:
        w.complete(_writeup(w.id))

    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.SYNTHESISING
    assert len(_writer_runs(core)) == 5  # polling did not re-request any


async def test_one_failed_write_up_drops_that_idea_and_names_it():
    core = FakeCoreGateway()
    svc, run, _ = await _to_writeups(core, 6)
    writers = _writer_runs(core)
    for w in writers:
        w.complete(_writeup(w.id))
    writers[2].fail()  # Idea 3

    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.COMPLETE
    assert state.failure_reason is not None and "Idea 3" in state.failure_reason
    stored = await svc.get_candidates(owner_sub=OWNER, run_id=run.id)
    assert [c.title for c in stored] == ["Idea 1", "Idea 2", "Idea 4", "Idea 5", "Idea 6"]


async def test_a_malformed_write_up_is_treated_like_a_failed_one():
    core = FakeCoreGateway()
    svc, run, _ = await _to_writeups(core, 5)
    writers = _writer_runs(core)
    for w in writers:
        w.complete(_writeup(w.id))
    writers[0].complete(_call(WRITEUP_TOOL_NAME, {"scorecard": {"nope": 1}}))

    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.COMPLETE
    assert "Idea 1" in (state.failure_reason or "")
    assert len(await svc.get_candidates(owner_sub=OWNER, run_id=run.id)) == 4


async def test_every_write_up_failing_fails_the_run_naming_them():
    core = FakeCoreGateway()
    svc, run, _ = await _to_writeups(core, 5)
    for w in _writer_runs(core):
        w.fail()

    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    assert "Idea 1" in (state.failure_reason or "")


async def test_findings_message_helper_still_matches_the_research_contract():
    # Guards the fakes this file leans on from drifting under it.
    assert findings_message()[0]["tool_calls"][0]["function"]["name"] == (
        "submit_research_findings"
    )


async def test_a_ranking_call_with_an_invalid_shortlist_fails_the_run():
    core = FakeCoreGateway()
    svc = _service(core)
    run = await svc.start_run(owner_sub=OWNER, build_type="micro-saas", complexity=3)
    for rid, angle in zip(
        run.research_run_ids, ("community", "narrative", "competitive"), strict=True
    ):
        core.agent_runs[rid].complete(_big_findings(angle))
    core.engine_fires_synthesis(run.id).complete(
        _call(CANDIDATES_TOOL_NAME, {"ideas": "not a list"})
    )
    await svc.get_run(owner_sub=OWNER, run_id=run.id)

    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    assert "nothing usable" in (state.failure_reason or "")


async def test_a_legacy_full_set_call_with_invalid_candidates_fails_the_run():
    core = FakeCoreGateway()
    svc = _service(core)
    run = await svc.start_run(owner_sub=OWNER, build_type="micro-saas", complexity=3)
    for rid, angle in zip(
        run.research_run_ids, ("community", "narrative", "competitive"), strict=True
    ):
        core.agent_runs[rid].complete(_big_findings(angle))
    core.engine_fires_synthesis(run.id).complete(
        _call(CANDIDATES_TOOL_NAME, {"candidates": "not a list"})
    )
    await svc.get_run(owner_sub=OWNER, run_id=run.id)

    state = await svc.get_run(owner_sub=OWNER, run_id=run.id)

    assert state.status == m.FAILED
    assert "nothing usable" in (state.failure_reason or "")
