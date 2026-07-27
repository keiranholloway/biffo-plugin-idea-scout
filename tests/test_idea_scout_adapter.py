"""Tests for the HTTP adapter — the mapping onto Core's seams.

These assert the things a service-level test cannot see: which URL was called,
what was in the body, and how the Text-columns-holding-JSON round-trip works.
Getting any of it wrong fails only against a real Core, so it is asserted here.
"""

from __future__ import annotations

import json

import pytest
from fakes import FakeTransport

from idea_scout import adapter
from idea_scout.adapter import CoreHttpGateway, CoreNotFoundError
from idea_scout.models import RESEARCHING

RUNS = "/api/v1/internal/owner-data/idea_scout_runs"
CANDIDATES = "/api/v1/internal/owner-data/idea_scout_candidates"
AGENT_RUNS = "/api/v1/internal/agent-runs"
PROFILE = "/api/v1/internal/user-profile/mine"
CONFIG = "/api/v1/internal/plugins/me/config"
BUILD_TYPES = "/api/v1/internal/plugins/idea-scout/build-types"


def _row(**overrides):
    row = {
        "id": "run-1",
        "owner_sub": "founder-sub-abc",
        "build_type": "micro-saas",
        "complexity": 3,
        "chain_id": "chain-1",
        "status": RESEARCHING,
        "research_run_ids": json.dumps(["a", "b", "c"]),
        "profile_snapshot": json.dumps({"headline": "Fractional CTO"}),
        "synthesis_run_id": None,
        "failure_reason": None,
        "created_at": "2026-07-27T00:00:00Z",
        "deleted": False,
    }
    row.update(overrides)
    return row


# ── The founder's profile ────────────────────────────────────────────────────


async def test_profile_reads_the_internal_seam():
    transport = FakeTransport({("GET", PROFILE): {"headline": "Fractional CTO"}})
    profile = await CoreHttpGateway(transport).get_user_profile(owner_sub="founder-sub-abc")

    assert transport.last("GET", PROFILE)["path"] == PROFILE
    assert profile.headline == "Fractional CTO"


async def test_profile_never_sends_an_owner():
    """Core stamps the owner from the forwarded token. Sending one would be a
    way to ask for somebody else's profile."""
    transport = FakeTransport({("GET", PROFILE): {}})
    await CoreHttpGateway(transport).get_user_profile(owner_sub="founder-sub-abc")

    call = transport.last("GET", PROFILE)
    assert call["json"] is None
    assert call["params"] is None


async def test_an_all_empty_profile_is_not_an_error():
    transport = FakeTransport({("GET", PROFILE): {}})
    profile = await CoreHttpGateway(transport).get_user_profile(owner_sub="x")
    assert profile.is_empty is True


async def test_a_missing_profile_seam_surfaces_rather_than_reading_as_empty():
    """A 404 here means an un-upgraded Core, not a founder with no profile —
    silently returning empty would make a broken read look like a thin one."""
    transport = FakeTransport()
    transport.not_found.add(("GET", PROFILE))

    with pytest.raises(CoreNotFoundError):
        await CoreHttpGateway(transport).get_user_profile(owner_sub="x")


# ── Every seam this adapter reaches for ──────────────────────────────────────


def test_every_adapter_path_targets_cores_internal_seam():
    """Not style — the one thing that made every scout run 500 (#17).

    ``/api/v1/plugins/*`` is routed by API Gateway to the shared plugin host
    (ADR-0021), never to Core. A path under it therefore comes back into this
    plugin's own host, whose founder gate reads ``Authorization``/
    ``X-Biffo-Founder-Token`` — not the ``X-Biffo-User-Token`` CoreTransport
    forwards — so the call 401s. Core mounts the same declared routes under
    ``/api/v1/internal/`` for exactly this caller (Core's #652 mount).

    Asserted over the module's constants rather than per-call, so a *new* seam
    added later cannot reintroduce this without failing here. The per-endpoint
    tests below cannot catch it: they assert against these same constants, so
    they pass whatever the constant says.
    """
    paths = {
        name: value
        for name, value in vars(adapter).items()
        if name.isupper() and isinstance(value, str) and value.startswith("/api/")
    }

    assert paths, "no adapter paths found — did the constants move or get renamed?"
    assert adapter._ROOT == "/api/v1/internal"
    assert [n for n, p in paths.items() if not p.startswith(adapter._ROOT)] == []


# ── Build types ──────────────────────────────────────────────────────────────


async def test_build_types_are_filtered_and_ordered():
    transport = FakeTransport(
        {
            ("GET", BUILD_TYPES): [
                {"id": "3", "key": "c", "label": "Zebra", "active": True, "sort_order": 2},
                {"id": "1", "key": "a", "label": "Apple", "active": True, "sort_order": 1},
                {"id": "2", "key": "b", "label": "Banana", "active": False, "sort_order": 0},
            ]
        }
    )
    types = await CoreHttpGateway(transport).list_build_types()

    assert [t.key for t in types] == ["a", "c"]


async def test_build_types_without_a_sort_order_fall_back_to_label():
    transport = FakeTransport(
        {
            ("GET", BUILD_TYPES): [
                {"id": "1", "key": "b", "label": "Banana", "active": True},
                {"id": "2", "key": "a", "label": "Apple", "active": True},
            ]
        }
    )
    types = await CoreHttpGateway(transport).list_build_types()

    assert [t.label for t in types] == ["Apple", "Banana"]


async def test_inactive_build_types_can_be_included_for_an_admin_view():
    transport = FakeTransport(
        {("GET", BUILD_TYPES): [{"id": "1", "key": "a", "label": "A", "active": False}]}
    )
    types = await CoreHttpGateway(transport).list_build_types(active_only=False)
    assert len(types) == 1


async def test_a_null_active_column_reads_as_inactive():
    """The column is nullable because migration DDL doesn't apply defaults —
    NULL must not read as 'offered'."""
    transport = FakeTransport({("GET", BUILD_TYPES): [{"id": "1", "key": "a", "label": "A"}]})
    assert await CoreHttpGateway(transport).list_build_types() == []


# ── Agent runs ───────────────────────────────────────────────────────────────


async def test_an_agent_run_is_created_without_a_thread():
    """Idea Scout has no conversation; the whole context is input_payload.
    Sending a thread_id would make Core assemble a transcript that doesn't exist."""
    transport = FakeTransport({("POST", AGENT_RUNS): {"id": "agent-1"}})
    await CoreHttpGateway(transport).request_agent_run(
        agent_name="idea-scout-community",
        definition={"model": "m", "tools": ["web_search"], "max_turns": 8},
        output_tool={"type": "function", "function": {"name": "submit_research_findings"}},
        input_payload={"brief": {"build_type": {"key": "micro-saas"}}},
        causation_id="chain-1",
    )

    body = transport.last("POST", AGENT_RUNS)["json"]
    assert "thread_id" not in body
    assert body["agent_name"] == "idea-scout-community"
    # The chain is what makes sibling research runs a set the engine's fan-in
    # can recognise; without it each would be its own root.
    assert body["causation_id"] == "chain-1"
    assert body["input_payload"]["brief"]["build_type"]["key"] == "micro-saas"


async def test_the_output_tool_rides_on_the_snapshot_not_the_tool_registry():
    """Listing it in `tools` would fail the whole run as an unknown tool."""
    transport = FakeTransport({("POST", AGENT_RUNS): {"id": "agent-1"}})
    await CoreHttpGateway(transport).request_agent_run(
        agent_name="a",
        definition={"model": "m", "tools": ["web_search"]},
        output_tool={"type": "function", "function": {"name": "submit_research_findings"}},
        input_payload={},
        causation_id="chain-1",
    )

    snapshot = transport.last("POST", AGENT_RUNS)["json"]["definition_snapshot"]
    assert snapshot["tools"] == ["web_search"]
    assert snapshot["output_tools"][0]["function"]["name"] == "submit_research_findings"


async def test_a_run_core_does_not_know_reads_as_none():
    transport = FakeTransport()
    transport.not_found.add(("GET", f"{AGENT_RUNS}/gone"))
    assert await CoreHttpGateway(transport).get_agent_run(run_id="gone") is None


async def test_the_run_model_falls_back_to_the_snapshot():
    transport = FakeTransport(
        {
            ("GET", f"{AGENT_RUNS}/r"): {
                "id": "r",
                "status": "completed",
                "messages": [],
                "definition_snapshot": {"model": "from-snapshot"},
            }
        }
    )
    view = await CoreHttpGateway(transport).get_agent_run(run_id="r")
    assert view is not None
    assert view.model == "from-snapshot"


# ── Runs: the JSON-in-Text round trip ────────────────────────────────────────


async def test_creating_a_run_serialises_the_json_columns_and_sends_no_owner():
    transport = FakeTransport({("POST", RUNS): _row()})
    await CoreHttpGateway(transport).create_run(
        owner_sub="founder-sub-abc",
        build_type="micro-saas",
        complexity=3,
        profile_snapshot={"headline": "Fractional CTO"},
        research_run_ids=["a", "b", "c"],
        chain_id="chain-1",
    )

    body = transport.last("POST", RUNS)["json"]
    assert "owner_sub" not in body
    assert body["chain_id"] == "chain-1"
    assert body["status"] == RESEARCHING
    # Text columns: strings on the wire, not nested JSON.
    assert body["research_run_ids"] == json.dumps(["a", "b", "c"])
    assert json.loads(body["profile_snapshot"]) == {"headline": "Fractional CTO"}


async def test_reading_a_run_parses_the_json_columns_back():
    transport = FakeTransport({("GET", f"{RUNS}/run-1"): _row()})
    run = await CoreHttpGateway(transport).get_run(owner_sub="x", run_id="run-1")

    assert run is not None
    assert run.research_run_ids == ["a", "b", "c"]
    assert run.profile_snapshot == {"headline": "Fractional CTO"}


async def test_null_json_columns_read_as_sensible_empties():
    transport = FakeTransport(
        {("GET", f"{RUNS}/run-1"): _row(research_run_ids=None, profile_snapshot=None)}
    )
    run = await CoreHttpGateway(transport).get_run(owner_sub="x", run_id="run-1")

    assert run is not None
    assert run.research_run_ids == []
    assert run.profile_snapshot is None


async def test_a_corrupt_json_column_degrades_instead_of_500ing_the_listing():
    """One bad row shouldn't take out a founder's whole sidebar."""
    transport = FakeTransport({("GET", RUNS): [_row(research_run_ids="{not json")]})
    runs = await CoreHttpGateway(transport).list_runs(owner_sub="x")

    assert runs[0].research_run_ids == []


async def test_an_already_parsed_column_is_passed_through():
    """Tolerates a transport that parsed the JSON itself."""
    transport = FakeTransport({("GET", f"{RUNS}/run-1"): _row(research_run_ids=["a"])})
    run = await CoreHttpGateway(transport).get_run(owner_sub="x", run_id="run-1")
    assert run is not None
    assert run.research_run_ids == ["a"]


async def test_a_missing_run_reads_as_none():
    transport = FakeTransport()
    transport.not_found.add(("GET", f"{RUNS}/gone"))
    assert await CoreHttpGateway(transport).get_run(owner_sub="x", run_id="gone") is None


async def test_updating_a_run_patches_and_serialises_json_fields():
    transport = FakeTransport()
    gateway = CoreHttpGateway(transport)

    await gateway.update_run(run_id="run-1", status="synthesising", synthesis_run_id="s-1")
    call = transport.last("PATCH", f"{RUNS}/run-1")
    assert call["json"] == {"status": "synthesising", "synthesis_run_id": "s-1"}

    await gateway.update_run(run_id="run-1", research_run_ids=["a"])
    assert transport.last("PATCH", f"{RUNS}/run-1")["json"]["research_run_ids"] == '["a"]'


async def test_an_already_serialised_json_field_is_not_double_encoded():
    transport = FakeTransport()
    await CoreHttpGateway(transport).update_run(run_id="run-1", research_run_ids='["a"]')
    assert transport.last("PATCH", f"{RUNS}/run-1")["json"]["research_run_ids"] == '["a"]'


async def test_listing_runs_sends_no_owner_filter():
    """Core's owner-data list route already scopes to the caller."""
    transport = FakeTransport({("GET", RUNS): []})
    await CoreHttpGateway(transport).list_runs(owner_sub="founder-sub-abc")

    call = transport.last("GET", RUNS)
    assert call["params"] is None
    assert call["json"] is None


# ── Candidates ───────────────────────────────────────────────────────────────


async def test_candidates_are_stored_one_per_row_with_their_rank():
    transport = FakeTransport({("POST", CANDIDATES): {}})
    await CoreHttpGateway(transport).save_candidates(
        run_id="run-1",
        candidates=[
            {"title": "First", "pitch": "p", "scorecard": {"summary": "s"}, "sources": []},
            {"title": "Second", "pitch": "p", "scorecard": {"summary": "s"}, "sources": []},
        ],
        model="test-model",
    )

    posts = [c for c in transport.calls if c["path"] == CANDIDATES]
    assert [p["json"]["rank"] for p in posts] == [1, 2]
    assert [p["json"]["title"] for p in posts] == ["First", "Second"]
    assert "owner_sub" not in posts[0]["json"]
    # Scorecard is a Text column, so it goes over as a JSON string.
    assert json.loads(posts[0]["json"]["scorecard"]) == {"summary": "s"}


async def test_candidates_are_read_back_in_rank_order():
    transport = FakeTransport(
        {
            ("GET", CANDIDATES): [
                {
                    "id": "c2",
                    "run_id": "run-1",
                    "rank": 2,
                    "title": "Second",
                    "pitch": "p",
                    "scorecard": '{"summary": "s"}',
                    "sources": "[]",
                },
                {
                    "id": "c1",
                    "run_id": "run-1",
                    "rank": 1,
                    "title": "First",
                    "pitch": "p",
                    "scorecard": None,
                    "sources": None,
                },
            ]
        }
    )
    candidates = await CoreHttpGateway(transport).list_candidates(owner_sub="x", run_id="run-1")

    assert [c.rank for c in candidates] == [1, 2]
    assert candidates[0].sources == []
    assert candidates[1].scorecard == {"summary": "s"}
    assert transport.last("GET", CANDIDATES)["params"] == {"run_id": "run-1"}


# ── Plugin config ────────────────────────────────────────────────────────────


async def test_an_unconfigured_role_reads_as_none():
    transport = FakeTransport()
    transport.not_found.add(("GET", f"{CONFIG}/idea-scout-community"))
    result = await CoreHttpGateway(transport).get_own_config(role="idea-scout-community")
    assert result is None


async def test_a_configured_role_returns_its_prompt_and_model():
    transport = FakeTransport(
        {("GET", f"{CONFIG}/x"): {"system_prompt": "custom", "model": "custom-model"}}
    )
    result = await CoreHttpGateway(transport).get_own_config(role="x")
    assert result == {"system_prompt": "custom", "model": "custom-model"}


# ── Finding what the engine created ──────────────────────────────────────────


async def test_finding_a_chain_run_queries_by_chain_and_agent():
    """How the plugin discovers the synthesis run the orchestration engine fired
    on its behalf — nothing tells it the id."""
    transport = FakeTransport(
        {
            ("GET", AGENT_RUNS): [{"id": "syn-1"}],
            ("GET", f"{AGENT_RUNS}/syn-1"): {
                "id": "syn-1",
                "status": "completed",
                "messages": [],
            },
        }
    )
    view = await CoreHttpGateway(transport).find_chain_run(
        chain_id="chain-1", agent_name="idea-scout-synthesis"
    )

    assert view is not None
    assert view.id == "syn-1"
    assert transport.calls[0]["params"] == {
        "causation_id": "chain-1",
        "agent_name": "idea-scout-synthesis",
    }


async def test_no_chain_run_yet_reads_as_none():
    """The normal case while the engine has not fired it — not an error."""
    transport = FakeTransport({("GET", AGENT_RUNS): []})
    assert await CoreHttpGateway(transport).find_chain_run(chain_id="c", agent_name="a") is None


async def test_finding_a_chain_run_fetches_it_in_full():
    """The chain listing carries summaries only; the caller needs the transcript
    to extract the structured output, so the full run is fetched."""
    transport = FakeTransport(
        {
            ("GET", AGENT_RUNS): [{"id": "syn-1"}],
            ("GET", f"{AGENT_RUNS}/syn-1"): {
                "id": "syn-1",
                "status": "completed",
                "messages": [{"role": "assistant"}],
            },
        }
    )
    view = await CoreHttpGateway(transport).find_chain_run(chain_id="c", agent_name="a")

    assert view is not None
    assert view.messages == [{"role": "assistant"}]
