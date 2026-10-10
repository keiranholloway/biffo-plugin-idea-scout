"""Compile the PRD draft, backend (#178 M4)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from biffo_plugin_sdk import ForwardedUser
from fakes import FakeCoreGateway, candidates_message
from fastapi.testclient import TestClient

from idea_scout.app import app, get_service, require_founder
from idea_scout.definitions import (
    PRD_TOOL_NAME,
    PRD_WRITER_AGENT_NAME,
    ProductRequirements,
    render_prd_markdown,
    seed_config_payloads,
)
from idea_scout.models import UserProfile
from idea_scout.service import IdeaScoutService

OWNER = "founder-a"
OTHER = "founder-b"
HEADINGS = [
    "Summary",
    "Problem",
    "Goals",
    "Non-Goals",
    "Personas",
    "User Stories",
    "Functional Requirements",
    "UX Surfaces",
    "Permissions",
    "Data Model Alignment",
    "API Expectations",
    "Events And Audit",
    "Success Metrics",
    "Edge Cases",
    "Open Questions",
    "Sources",
]


def _prd_args(title: str = "Invoice Chaser") -> dict[str, Any]:
    return {
        "title": title,
        "summary": "Chases late invoices.",
        "problem": "Freelancers get paid late.",
        "goals": ["Get paid faster"],
        "user_stories": [
            {
                "id": "US-01",
                "title": "Send reminder",
                "as_a": "freelancer",
                "i_want": "reminders sent",
                "so_that": "I get paid",
                "acceptance_criteria": ["A reminder goes out"],
            }
        ],
        "functional_requirements": [{"id": "FR-01", "area": "Reminders", "requirement": "Send."}],
        "sources": [{"url": "https://example.com", "note": "n"}],
    }


def _prd_message(arguments: Any = None, name: str = PRD_TOOL_NAME) -> list[dict[str, Any]]:
    args = _prd_args() if arguments is None else arguments
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }
    ]


@pytest.fixture
def core() -> FakeCoreGateway:
    gateway = FakeCoreGateway(profile=UserProfile(headline="CTO", focus_areas=["logistics"]))
    for row in seed_config_payloads(research_model="r/m", synthesis_model="s/m"):
        gateway.configs.setdefault(
            row["role"], {"system_prompt": row["system_prompt"], "model": row["model"]}
        )
    return gateway


def _client(core: FakeCoreGateway, sub: str) -> TestClient:
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub=sub, groups=["founder"], token="tok"
    )
    app.dependency_overrides[get_service] = lambda: IdeaScoutService(
        core, research_model="r/m", synthesis_model="s/m"
    )
    return TestClient(app)


@pytest.fixture
def client(core: FakeCoreGateway) -> Iterator[TestClient]:
    yield _client(core, OWNER)
    app.dependency_overrides.clear()


@pytest.fixture
def ids(client: TestClient, core: FakeCoreGateway) -> tuple[str, str]:
    """``(candidate_id, prd_id)`` for a PRD whose interview has started."""
    run_id = client.post("/runs", json={"build_type": "micro-saas", "complexity": 3}).json()[
        "run_id"
    ]
    core.complete_all_research(run_id)
    synthesis = core.engine_fires_synthesis(run_id)
    client.get(f"/runs/{run_id}")
    synthesis.complete(candidates_message(5))
    cid = client.get(f"/runs/{run_id}/candidates").json()["candidates"][0]["id"]
    return cid, client.post(f"/candidates/{cid}/prd").json()["id"]


def _writer_run(core: FakeCoreGateway):
    return [r for r in core.agent_runs.values() if r.agent_name == PRD_WRITER_AGENT_NAME][-1]


def test_draft_requests_the_writer_run_and_goes_drafting(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/messages", json={"message": "my answer"})
    resp = client.post(f"/prds/{pid}/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "drafting"
    run = _writer_run(core)
    assert body["compile_run_id"] == run.id
    req = core.requested[-1]
    assert req["agent_name"] == PRD_WRITER_AGENT_NAME
    assert req["output_tool"]["function"]["name"] == PRD_TOOL_NAME
    assert req["output_tool"]["function"]["parameters"] == ProductRequirements.model_json_schema()
    payload = req["input_payload"]
    assert set(payload) == {"dossier", "conversation", "previous_draft"}
    assert core.candidates[0].title in payload["dossier"]
    assert any(m["content"] == "my answer" for m in payload["conversation"])
    assert payload["previous_draft"] is None


def test_draft_while_drafting_is_409(client, core, ids):
    _, pid = ids
    client.post(f"/prds/{pid}/draft")
    before = len(core.requested)
    assert client.post(f"/prds/{pid}/draft").status_code == 409
    assert len(core.requested) == before


def test_happy_compile_is_collected_on_read(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    # Still running: nothing changes.
    assert client.get(f"/candidates/{cid}/prd").json()["status"] == "drafting"
    _writer_run(core).complete(_prd_message())
    body = client.get(f"/candidates/{cid}/prd").json()
    assert body["status"] == "draft"
    assert body["prd"]["title"] == "Invoice Chaser"
    assert body["failure_reason"] is None
    md = client.get(f"/candidates/{cid}/prd.md")
    assert md.status_code == 200
    for heading in HEADINGS:
        assert f"## {heading}" in md.text


def test_rendered_markdown_of_a_compiled_fixture_has_every_heading():
    from idea_scout.service import extract_prd

    text = render_prd_markdown(extract_prd(_prd_message()))
    for heading in HEADINGS:
        assert f"## {heading}" in text


def test_collected_on_the_prd_id_route_too(client, core, ids):
    _, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete(_prd_message())
    assert client.get(f"/prds/{pid}").json()["status"] == "draft"


def test_malformed_tool_call_fails_the_draft(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete(_prd_message({"title": 7, "goals": "nope"}))
    body = client.get(f"/candidates/{cid}/prd").json()
    assert body["status"] == "failed"
    assert body["failure_reason"]
    assert body["prd"] is None


def test_missing_tool_call_fails_the_draft(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete([{"role": "assistant", "content": "prose"}])
    assert client.get(f"/candidates/{cid}/prd").json()["status"] == "failed"


def test_failed_run_fails_the_draft(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).fail()
    body = client.get(f"/candidates/{cid}/prd").json()
    assert body["status"] == "failed"
    assert "failed to compile" in body["failure_reason"]


def test_never_started_run_fails_with_its_own_reason(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).never_claimed()
    body = client.get(f"/candidates/{cid}/prd").json()
    assert body["status"] == "failed"
    assert "never started" in body["failure_reason"]


def test_redraft_failure_keeps_the_previous_prd_and_sends_it(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete(_prd_message())
    first = client.get(f"/candidates/{cid}/prd").json()["prd"]

    client.post(f"/prds/{pid}/draft")
    assert core.requested[-1]["input_payload"]["previous_draft"] == first
    _writer_run(core).fail()
    body = client.get(f"/candidates/{cid}/prd").json()
    assert body["status"] == "failed"
    assert body["prd"] == first
    # A failed draft can be retried.
    assert client.post(f"/prds/{pid}/draft").status_code == 200


def test_finalise_from_draft(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete(_prd_message())
    resp = client.post(f"/prds/{pid}/finalise")
    assert resp.status_code == 200
    assert resp.json()["status"] == "final"
    assert client.get(f"/candidates/{cid}/prd").json()["status"] == "final"


def test_finalise_from_other_states_is_409(client, core, ids):
    cid, pid = ids
    assert client.post(f"/prds/{pid}/finalise").status_code == 409  # interviewing
    client.post(f"/prds/{pid}/draft")
    assert client.post(f"/prds/{pid}/finalise").status_code == 409  # drafting
    _writer_run(core).fail()
    assert client.post(f"/prds/{pid}/finalise").status_code == 409  # failed
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete(_prd_message())
    assert client.post(f"/prds/{pid}/finalise").status_code == 200
    assert client.post(f"/prds/{pid}/finalise").status_code == 409  # final


def test_chat_turn_after_final_returns_to_draft(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete(_prd_message())
    client.post(f"/prds/{pid}/finalise")
    resp = client.post(f"/prds/{pid}/messages", json={"message": "one more thing"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"
    body = client.get(f"/candidates/{cid}/prd").json()
    assert body["status"] == "draft"
    assert body["prd"]["title"] == "Invoice Chaser"


def test_new_draft_on_a_final_prd_ends_up_as_draft(client, core, ids):
    cid, pid = ids
    client.post(f"/prds/{pid}/draft")
    _writer_run(core).complete(_prd_message())
    client.post(f"/prds/{pid}/finalise")
    assert client.post(f"/prds/{pid}/draft").status_code == 200
    _writer_run(core).complete(_prd_message(_prd_args("Invoice Chaser v2")))
    body = client.get(f"/candidates/{cid}/prd").json()
    assert body["status"] == "draft"
    assert body["prd"]["title"] == "Invoice Chaser v2"


def test_another_founder_gets_404_on_the_new_routes(client, core, ids):
    _, pid = ids
    other = _client(core, OTHER)
    assert other.post(f"/prds/{pid}/draft").status_code == 404
    assert other.post(f"/prds/{pid}/finalise").status_code == 404
    assert other.get(f"/prds/{pid}").status_code == 404
    assert not [r for r in core.agent_runs.values() if r.agent_name == PRD_WRITER_AGENT_NAME]


def test_compile_input_is_size_bounded_for_a_full_size_dossier(client, core, ids):
    from dataclasses import replace

    from idea_scout.service import COMPILE_DOSSIER_MAX_CHARS, COMPILE_MESSAGE_MAX_CHARS

    cid, pid = ids
    core.candidates[0] = replace(core.candidates[0], sources=[{"u": "z" * 400}] * 200)
    client.post(f"/prds/{pid}/messages", json={"message": "long answer " + "w" * 9000})
    assert client.post(f"/prds/{pid}/draft").status_code == 200
    payload = core.requested[-1]["input_payload"]
    assert len(payload["dossier"]) <= COMPILE_DOSSIER_MAX_CHARS
    assert core.candidates[0].title in payload["dossier"]
    assert all(len(m["content"]) <= COMPILE_MESSAGE_MAX_CHARS for m in payload["conversation"])
