"""The founder-facing ASGI app (ADR-0021): routes, shapes and the error map.

The founder gate and the service factory are overridden so the app runs over the
in-memory fake Core — JWT verification lives in the SDK and the SigV4 transport
has its own tests. What is asserted here is what this layer actually owns: the
HTTP contract, the gate being present on every route, and errors becoming the
right statuses.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from biffo_plugin_sdk import ForwardedUser
from fakes import FakeCoreGateway, candidates_message
from fastapi.testclient import TestClient

from idea_scout import models as m
from idea_scout.app import app, get_service, require_founder
from idea_scout.models import BuildType, UserProfile
from idea_scout.service import IdeaScoutService

OWNER = "founder-sub-abc"


@pytest.fixture
def core() -> FakeCoreGateway:
    return FakeCoreGateway(
        profile=UserProfile(headline="Fractional CTO"),
        build_types=[
            BuildType(
                id="bt1",
                key="micro-saas",
                label="MicroSaaS",
                description="One narrow job, one buyer.",
                active=True,
                sort_order=1,
            ),
            BuildType(id="bt2", key="retired", label="Retired", active=False),
        ],
    )


@pytest.fixture
def client(core: FakeCoreGateway) -> Iterator[TestClient]:
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub=OWNER, groups=["founder"], token="tok"
    )
    app.dependency_overrides[get_service] = lambda: IdeaScoutService(
        core, research_model="research/m", synthesis_model="synthesis/m"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _start(client: TestClient, **overrides):
    body = {"build_type": "micro-saas", "complexity": 3}
    body.update(overrides)
    return client.post("/runs", json=body)


# ── Inputs ───────────────────────────────────────────────────────────────────


def test_build_types_lists_only_active_ones(client):
    resp = client.get("/build-types")

    assert resp.status_code == 200
    assert [t["key"] for t in resp.json()] == ["micro-saas"]
    assert resp.json()[0]["label"] == "MicroSaaS"


def test_complexity_levels_are_served_with_their_wording(client):
    """The frontend renders these rather than hardcoding them, so the words the
    founder reads are the words the agents are briefed with."""
    resp = client.get("/complexity-levels")

    assert resp.status_code == 200
    levels = resp.json()
    assert [level["value"] for level in levels] == [1, 2, 3, 4, 5]
    assert all(level["label"].strip() for level in levels)


# ── Starting a run ───────────────────────────────────────────────────────────


def test_starting_a_run_returns_its_state(client):
    resp = _start(client)

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == m.RESEARCHING
    assert body["in_flight"] is True
    assert body["build_type"] == "micro-saas"
    assert body["complexity"] == 3
    assert body["complexity_label"]
    assert body["run_id"]


def test_an_inactive_build_type_is_rejected(client):
    assert _start(client, build_type="retired").status_code == 422


def test_an_unknown_build_type_is_rejected(client):
    assert _start(client, build_type="invented").status_code == 422


@pytest.mark.parametrize("complexity", [0, 6, -1])
def test_complexity_outside_the_slider_is_rejected(client, complexity):
    """Bounded by the request model, so it never reaches the service."""
    assert _start(client, complexity=complexity).status_code == 422


def test_a_missing_build_type_is_rejected(client):
    assert client.post("/runs", json={"complexity": 3}).status_code == 422


# ── Reading runs ─────────────────────────────────────────────────────────────


def test_listing_runs_returns_them_most_recent_first(client):
    first = _start(client).json()["run_id"]
    second = _start(client).json()["run_id"]

    resp = client.get("/runs")

    assert resp.status_code == 200
    assert [r["run_id"] for r in resp.json()] == [second, first]


def test_reading_a_run_advances_it_when_the_agents_have_finished(client, core):
    """This is the polling endpoint, and polling is what moves a run forward."""
    run_id = _start(client).json()["run_id"]
    core.complete_all_research(run_id)
    core.engine_fires_synthesis(run_id)

    resp = client.get(f"/runs/{run_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == m.SYNTHESISING
    assert resp.json()["in_flight"] is True


def test_a_missing_run_is_a_404(client):
    assert client.get("/runs/nope").status_code == 404


def test_another_founders_run_is_a_404_not_a_403(client, core):
    """Indistinguishable from a run that does not exist — a 403 would confirm
    the id belongs to someone."""
    run_id = _start(client).json()["run_id"]
    core.runs[run_id] = replace(core.runs[run_id], owner_sub="someone-else")

    assert client.get(f"/runs/{run_id}").status_code == 404
    assert client.get(f"/runs/{run_id}/candidates").status_code == 404
    assert client.post(f"/runs/{run_id}/delete").status_code == 404


# ── Candidates ───────────────────────────────────────────────────────────────


def test_candidates_are_empty_while_the_run_is_in_flight(client):
    run_id = _start(client).json()["run_id"]

    resp = client.get(f"/runs/{run_id}/candidates")

    assert resp.status_code == 200
    assert resp.json()["candidates"] == []
    assert resp.json()["in_flight"] is True


def test_candidates_come_back_ranked_once_the_run_completes(client, core):
    run_id = _start(client).json()["run_id"]
    core.complete_all_research(run_id)
    synthesis = core.engine_fires_synthesis(run_id)
    client.get(f"/runs/{run_id}")  # picks up the engine's synthesis run
    synthesis.complete(candidates_message(5))

    resp = client.get(f"/runs/{run_id}/candidates")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == m.COMPLETE
    assert body["in_flight"] is False
    assert [c["rank"] for c in body["candidates"]] == [1, 2, 3, 4, 5]
    first = body["candidates"][0]
    assert first["title"] and first["pitch"]
    assert first["scorecard"]["viability"]["score"]
    assert first["sources"]


def test_the_candidates_endpoint_alone_is_enough_to_drive_the_run(client, core):
    """A client may poll only this one; it must still make progress and still
    report the run's state."""
    run_id = _start(client).json()["run_id"]
    core.complete_all_research(run_id)
    synthesis = core.engine_fires_synthesis(run_id)

    assert client.get(f"/runs/{run_id}/candidates").json()["status"] == m.SYNTHESISING

    synthesis.complete(candidates_message(5))
    assert client.get(f"/runs/{run_id}/candidates").json()["status"] == m.COMPLETE


def test_a_failed_run_reports_a_reason_rather_than_an_error_status(client, core):
    """Agent failure is a run state the founder can read, not a 5xx."""
    run_id = _start(client).json()["run_id"]
    for agent_run in core.research_runs_for(run_id):
        agent_run.fail()

    resp = client.get(f"/runs/{run_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == m.FAILED
    assert body["in_flight"] is False
    assert body["failure_reason"]


# ── Deleting ─────────────────────────────────────────────────────────────────


def test_deleting_a_run_removes_it_from_the_list(client):
    run_id = _start(client).json()["run_id"]

    assert client.post(f"/runs/{run_id}/delete").status_code == 204
    assert client.get("/runs").json() == []
    assert client.get(f"/runs/{run_id}").status_code == 404


def test_deleting_an_unknown_run_is_a_404(client):
    assert client.post("/runs/nope/delete").status_code == 404


# ── The gate ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/build-types"),
        ("GET", "/complexity-levels"),
        ("POST", "/runs"),
        ("GET", "/runs"),
        ("GET", "/runs/r1"),
        ("GET", "/runs/r1/candidates"),
        ("POST", "/runs/r1/delete"),
    ],
)
def test_every_route_is_gated(method, path):
    """Defence-in-depth behind the host's own group gate. Asserted per route
    rather than in aggregate, so a route added without the dependency fails
    here rather than shipping open."""
    app.dependency_overrides.clear()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.request(method, path, json={})

    assert resp.status_code == 401, f"{method} {path} was not gated"


def test_exposes_an_asgi_app_not_a_lambda_handler():
    """Under ADR-0021 the shared plugin host provides the Lambda entrypoint and
    mounts this app, stripping the prefix — so this module must export `app`
    and must not carry a Mangum handler of its own."""
    import idea_scout.app as module

    assert hasattr(module, "app")
    assert not hasattr(module, "handler")
