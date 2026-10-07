"""PRD interview chat, backend (#178 M3)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from biffo_plugin_sdk import ForwardedUser
from fakes import FakeCoreGateway, candidates_message
from fastapi.testclient import TestClient

from idea_scout.adapter import CoreHttpGateway
from idea_scout.app import app, get_service, require_founder
from idea_scout.definitions import (
    PRD_DOSSIER_MARKER,
    PRD_INTERVIEWER_AGENT_NAME,
    PRD_MAX_TURNS,
    seed_config_payloads,
)
from idea_scout.models import UserProfile
from idea_scout.service import IdeaScoutService

OWNER = "founder-a"
OTHER = "founder-b"


@pytest.fixture
def core() -> FakeCoreGateway:
    gateway = FakeCoreGateway(
        profile=UserProfile(headline="Fractional CTO", focus_areas=["logistics"])
    )
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
def candidate_id(client: TestClient, core: FakeCoreGateway) -> str:
    run_id = client.post("/runs", json={"build_type": "micro-saas", "complexity": 3}).json()[
        "run_id"
    ]
    core.complete_all_research(run_id)
    synthesis = core.engine_fires_synthesis(run_id)
    client.get(f"/runs/{run_id}")
    synthesis.complete(candidates_message(5))
    return client.get(f"/runs/{run_id}/candidates").json()["candidates"][0]["id"]


def test_dossier_opening_message_contains_every_input(client, core, candidate_id):
    resp = client.post(f"/candidates/{candidate_id}/prd")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "interviewing"
    assert body["turn_count"] == 1

    turn = core.chat_turns[0]
    assert turn["agent_name"] == PRD_INTERVIEWER_AGENT_NAME
    dossier = turn["message"]
    cand = core.candidates[0]
    assert dossier.startswith(PRD_DOSSIER_MARKER)
    assert cand.title in dossier
    assert cand.pitch in dossier
    for axis in ("viability", "complexity", "economic_moat", "market_fit"):
        assert axis in dossier
    assert "Build — nothing existing fits." in dossier
    assert "https://example.com/a" in dossier
    run = next(iter(core.runs.values()))
    for angle_run in core.research_runs_for(run.id):
        assert f"{angle_run.agent_name} signal" in dossier
        assert "People are working around it manually." in dossier
    assert "Fractional CTO" in dossier
    assert "logistics" in dossier
    assert "micro-saas" in dossier
    assert "no preference" in dossier  # business model absent on this run


def test_dossier_carries_the_business_model(client, core, candidate_id):
    run = next(iter(core.runs.values()))
    core.runs[run.id] = replace(run, business_model="subscription")
    client.post(f"/candidates/{candidate_id}/prd")
    assert "subscription" in core.chat_turns[0]["message"]


def test_creating_the_row_writes_every_column(client, core, candidate_id):
    client.post(f"/candidates/{candidate_id}/prd")
    (owner, prd) = core.prds[0]
    assert owner == OWNER
    assert prd.thread_id
    assert prd.deleted is False
    assert prd.compile_run_id is None and prd.prd is None and prd.failure_reason is None


def test_resume_does_not_create_a_second_thread(client, core, candidate_id):
    first = client.post(f"/candidates/{candidate_id}/prd").json()
    second = client.post(f"/candidates/{candidate_id}/prd").json()
    assert second["id"] == first["id"]
    assert second["thread_id"] == first["thread_id"]
    assert len(core.prds) == 1
    assert len(core.chat_turns) == 1
    assert len(core.threads) == 1


def test_resume_retries_an_opening_turn_that_never_completed_on_the_same_thread(
    client, core, candidate_id
):
    first = client.post(f"/candidates/{candidate_id}/prd").json()
    owner, prd = core.prds[0]
    core.prds[0] = (owner, replace(prd, turn_count=0))
    core.threads.clear()
    again = client.post(f"/candidates/{candidate_id}/prd").json()
    assert again["thread_id"] == first["thread_id"]
    assert len(core.prds) == 1
    assert again["turn_count"] == 1


def test_turn_16_is_409(client, core, candidate_id):
    pid = client.post(f"/candidates/{candidate_id}/prd").json()["id"]
    for n in range(2, PRD_MAX_TURNS + 1):
        resp = client.post(f"/prds/{pid}/messages", json={"message": f"answer {n}"})
        assert resp.status_code == 200, n
        assert resp.json()["turn_count"] == n
    assert PRD_MAX_TURNS == 15
    resp = client.post(f"/prds/{pid}/messages", json={"message": "one more"})
    assert resp.status_code == 409
    assert len(core.chat_turns) == PRD_MAX_TURNS


def test_send_while_drafting_is_409(client, core, candidate_id):
    pid = client.post(f"/candidates/{candidate_id}/prd").json()["id"]
    owner, prd = core.prds[0]
    core.prds[0] = (owner, replace(prd, status="drafting"))
    resp = client.post(f"/prds/{pid}/messages", json={"message": "hi"})
    assert resp.status_code == 409
    assert len(core.chat_turns) == 1


def test_transcript_hides_the_dossier_and_keeps_order(client, core, candidate_id):
    pid = client.post(f"/candidates/{candidate_id}/prd").json()["id"]
    reply = client.post(f"/prds/{pid}/messages", json={"message": "my answer"}).json()["reply"]
    messages = client.get(f"/prds/{pid}/messages").json()["messages"]
    assert [m["role"] for m in messages] == ["assistant", "user", "assistant"]
    assert messages[1]["content"] == "my answer"
    assert messages[2]["content"] == reply
    assert all(PRD_DOSSIER_MARKER not in m["content"] for m in messages)


def test_another_founders_prd_is_404_on_all_three_routes(client, core, candidate_id):
    pid = client.post(f"/candidates/{candidate_id}/prd").json()["id"]
    other = _client(core, OTHER)
    assert other.post(f"/candidates/{candidate_id}/prd").status_code == 404
    assert other.post(f"/prds/{pid}/messages", json={"message": "x"}).status_code == 404
    assert other.get(f"/prds/{pid}/messages").status_code == 404
    assert len(core.chat_turns) == 1


# ── The adapter against Core's real thread-messages shape ────────────────────


class _Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def request(self, method, path, *, json=None, params=None):
        self.calls.append((method, path, json))
        return self.response


async def test_adapter_reads_core_thread_messages_shape():
    # Core's ThreadMessagesResponse: {thread_id, messages: [{role, content}]}.
    transport = _Transport(
        {
            "thread_id": "t1",
            "messages": [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
            ],
        }
    )
    gw = CoreHttpGateway(transport)
    msgs = await gw.read_thread_messages(thread_id="t1")
    assert msgs == [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"}]
    assert transport.calls[0][:2] == ("GET", "/api/v1/internal/agent-runs/threads/t1/messages")


async def test_adapter_chat_turn_posts_message_and_thread():
    transport = _Transport({"reply": "hello", "model": "m"})
    gw = CoreHttpGateway(transport)
    reply = await gw.run_chat_turn(
        agent_name=PRD_INTERVIEWER_AGENT_NAME, thread_id="t1", message="x"
    )
    assert reply == "hello"
    assert transport.calls[0] == (
        "POST",
        f"/api/v1/internal/agent-chat/{PRD_INTERVIEWER_AGENT_NAME}",
        {"message": "x", "thread_id": "t1"},
    )


async def test_adapter_create_prd_writes_every_column_and_no_owner():
    transport = _Transport(
        {"id": "p1", "candidate_id": "c", "run_id": "r", "status": "interviewing"}
    )
    await CoreHttpGateway(transport).create_prd(
        owner_sub="o", candidate_id="c", run_id="r", thread_id="t"
    )
    body = transport.calls[0][2]
    assert "owner_sub" not in body
    assert body == {
        "candidate_id": "c",
        "run_id": "r",
        "status": "interviewing",
        "thread_id": "t",
        "turn_count": 0,
        "compile_run_id": None,
        "prd": None,
        "failure_reason": None,
        "deleted": False,
    }


# ── Core's 16,000-character chat limit ───────────────────────────────────────


def _full_size_candidate_inputs():
    """A full-size candidate shaped like scout run 484baccb-… (7 candidates, 5
    research angles of ~14 long findings each, profile, many sources). Built
    synthetically: dev data cannot be captured from this sandbox."""
    from idea_scout.models import Candidate, ScoutRun

    candidate = Candidate(
        id="c1",
        run_id="r1",
        rank=1,
        title="Terms-Aware Invoice Reminder for QuickBooks Online",
        pitch="Reminders that read each customer's payment terms. " * 8,
        scorecard={"demand": 8, "feasibility": 7, "novelty": 6, "notes": "solid " * 40},
        sources=[
            {"url": f"https://example.com/source/{i}", "title": f"Source {i}", "note": "n" * 300}
            for i in range(25)
        ],
    )
    run = ScoutRun(
        id="r1",
        owner_sub=OWNER,
        build_type="micro-saas",
        complexity=3,
        chain_id="ch",
        status="complete",
        profile_snapshot={"headline": "Fractional CTO", "bio": "b" * 3000},
        business_model="subscription",
    )
    research = [
        {
            "angle": f"angle-{a}",
            "status": "succeeded",
            "findings": [
                {"claim": f"finding {a}.{i} " + "x" * 700, "source": f"https://e.com/{a}/{i}"}
                for i in range(14)
            ],
        }
        for a in range(5)
    ]
    linked = {"report": {"text": "r" * 6000}, "research": {"text": "s" * 6000}}
    return candidate, run, research, linked


def test_full_size_dossier_fits_core_limit_and_keeps_the_essentials():
    from idea_scout.service import CORE_CHAT_MESSAGE_LIMIT, _build_dossier

    candidate, run, research, linked = _full_size_candidate_inputs()
    unbounded = _build_dossier(candidate=candidate, run=run, research=research, linked=linked)
    assert len(unbounded) > 16_000  # the bug's precondition

    dossier = _build_dossier(
        candidate=candidate,
        run=run,
        research=research,
        linked=linked,
        max_chars=CORE_CHAT_MESSAGE_LIMIT,
    )
    assert len(dossier) <= 16_000
    assert dossier.startswith(PRD_DOSSIER_MARKER)
    assert candidate.title in dossier
    assert candidate.pitch in dossier
    assert "## Scorecard" in dossier
    assert '"demand": 8' in dossier
    assert "## Research findings" in dossier
    assert "angle-0" in dossier


def test_opening_message_sent_to_core_is_within_the_limit(client, core, candidate_id):
    cand = core.candidates[0]
    core.candidates[0] = replace(cand, pitch=cand.pitch, sources=[{"u": "z" * 400}] * 60)
    resp = client.post(f"/candidates/{candidate_id}/prd")
    assert resp.status_code == 200
    assert len(core.chat_turns[0]["message"]) <= 16_000


def test_core_422_on_interview_start_is_a_clear_4xx(client, core, candidate_id, monkeypatch):
    from idea_scout.adapter import CoreHttpError

    async def reject(**_kwargs):
        raise CoreHttpError("POST /agent-chat/x -> 422: string_too_long")

    monkeypatch.setattr(core, "run_chat_turn", reject)
    resp = client.post(f"/candidates/{candidate_id}/prd")
    assert resp.status_code == 422
    assert "could not be started" in resp.json()["detail"]


def test_other_core_failure_on_interview_start_is_a_clear_502(
    client, core, candidate_id, monkeypatch
):
    from idea_scout.adapter import CoreHttpError

    async def boom(**_kwargs):
        raise CoreHttpError("POST /agent-chat/x -> 500: boom")

    monkeypatch.setattr(core, "run_chat_turn", boom)
    resp = client.post(f"/candidates/{candidate_id}/prd")
    assert resp.status_code == 502
    assert "could not be started" in resp.json()["detail"]
