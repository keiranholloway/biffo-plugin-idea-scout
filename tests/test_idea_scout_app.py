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


# ── Preferences reach the service (#34) ──────────────────────────────────────
#
# These exist because the transport layer is where the feature actually broke.
# The service tests called `start_run` with preferences directly, and the
# frontend tests asserted `onStart` received them — so both ends were covered
# and the seam between them was not. The deployed API accepted the keys,
# validated them, echoed an empty list back, and silently discarded the input,
# because `app.py` never passed `body.preferences` to the service.


def test_the_posted_preferences_reach_the_service(client, core):
    """The gap the earlier tests left. Asserted through what the SERVICE was
    asked to do, not through the response, because the response echoed a stored
    value and looked plausible while the input was being dropped."""
    _start(client, preferences=["recurring-revenue", "regulated-markets"])

    run = next(iter(core.runs.values()))
    assert run.preferences == ["recurring-revenue", "regulated-markets"]


def test_the_posted_preferences_reach_the_agents(client, core):
    """One step further out: into the brief the research agents are given.
    Storing them without briefing on them would be the #26 failure again."""
    _start(client, preferences=["recurring-revenue"])

    briefs = [r["input_payload"]["brief"] for r in core.requested if "brief" in r["input_payload"]]
    assert briefs, "no research agent was briefed"
    assert briefs[0]["preferences"] == [
        {"key": "recurring-revenue", "direction": "prefer", "label": "Recurring revenue"}
    ]


def test_the_response_echoes_what_was_actually_stored(client):
    resp = _start(client, preferences=["rapid-validation"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["preferences"] == ["rapid-validation"]


def test_omitting_preferences_is_accepted_and_stores_none(client, core):
    resp = _start(client)
    assert resp.status_code == 201, resp.text
    assert resp.json()["preferences"] == []
    assert next(iter(core.runs.values())).preferences == []


def test_an_unknown_preference_key_is_refused(client):
    """422, not silently dropped — the prompts weigh by meaning and cannot
    honour a key they do not know."""
    resp = _start(client, preferences=["prefer-purple"])
    assert resp.status_code == 422
    assert "prefer-purple" in resp.text


def test_the_preferences_endpoint_lists_all_ten_with_directions(client):
    resp = client.get("/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 10
    assert {p["direction"] for p in body} == {"prefer", "avoid"}
    assert all({"key", "direction", "label"} <= set(p) for p in body)


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


# ── Model catalog (M1) ──────────────────────────────────────────────────────


def test_get_models_excludes_inactive_entries(client, core):
    """Only active models that support web search should be listed."""
    from idea_scout.models import ModelCatalogEntry

    core.model_catalog = [
        ModelCatalogEntry(
            id="m1",
            model_id="openai/gpt-4:online",
            label="GPT-4",
            active=True,
            is_default=True,
            web_capable=True,
        ),
        ModelCatalogEntry(
            id="m2",
            model_id="anthropic/claude-opus:online",
            label="Claude Opus",
            active=True,
            is_default=False,
            web_capable=True,
        ),
        ModelCatalogEntry(
            id="m3",
            model_id="anthropic/claude-sonnet",
            label="Claude Sonnet",
            active=True,
            is_default=False,
            web_capable=False,
        ),
        ModelCatalogEntry(
            id="m4",
            model_id="anthropic/claude-haiku:online",
            label="Claude Haiku",
            active=False,
            is_default=False,
            web_capable=True,
        ),
    ]

    resp = client.get("/models")
    assert resp.status_code == 200
    models = resp.json()
    # Should include only active AND web_capable
    assert len(models) == 2
    model_ids = {m["model_id"] for m in models}
    assert model_ids == {
        "openai/gpt-4:online",
        "anthropic/claude-opus:online",
    }


def test_get_models_returns_model_details(client, core):
    """The models endpoint returns enough info for the UI."""
    from idea_scout.models import ModelCatalogEntry

    core.model_catalog = [
        ModelCatalogEntry(
            id="m1",
            model_id="openai/gpt-4:online",
            label="GPT-4",
            active=True,
            is_default=True,
            web_capable=True,
        ),
    ]

    resp = client.get("/models")
    assert resp.status_code == 200
    models = resp.json()
    model = models[0]
    assert model["model_id"] == "openai/gpt-4:online"
    assert model["label"] == "GPT-4"
    assert model["is_default"] is True


def test_start_run_accepts_research_model_parameter(client, core):
    """The research_model field can be passed in the start run request."""
    from idea_scout.models import ModelCatalogEntry

    core.model_catalog = [
        ModelCatalogEntry(
            id="m1",
            model_id="openai/gpt-4:online",
            label="GPT-4",
            active=True,
            is_default=True,
            web_capable=True,
        ),
    ]

    resp = _start(client, research_model="m1")
    assert resp.status_code == 201, resp.text
    run = resp.json()
    # Stored as the model_id slug, not the catalog entry id
    assert run["research_model"] == "openai/gpt-4:online"


def test_start_run_rejects_non_web_capable_model(client, core):
    """Models without web search cannot be used."""
    from idea_scout.models import ModelCatalogEntry

    core.model_catalog = [
        ModelCatalogEntry(
            id="m1",
            model_id="anthropic/claude-sonnet",
            label="Claude Sonnet",
            active=True,
            is_default=False,
            web_capable=False,
        ),
    ]

    resp = _start(client, research_model="m1")
    assert resp.status_code == 422


def test_last_used_model_from_most_recent_run(client, core):
    """A founder's most recent run's model should be available for pre-selection."""
    from idea_scout.models import ModelCatalogEntry

    core.model_catalog = [
        ModelCatalogEntry(
            id="m1",
            model_id="openai/gpt-4:online",
            label="GPT-4",
            active=True,
            is_default=True,
            web_capable=True,
        ),
    ]

    # Start first run without a model
    resp1 = _start(client)
    assert resp1.status_code == 201

    # Start second run with a model
    resp2 = _start(client, research_model="m1")
    assert resp2.status_code == 201

    # List runs should show the most recent one with the model slug
    resp = client.get("/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) > 0
    # Most recent run should have the model slug (m1 -> openai/gpt-4:online)
    assert runs[0]["research_model"] == "openai/gpt-4:online"


def test_last_used_model_does_not_leak_between_founders(client, core):
    """One founder's runs should not affect another founder's model suggestions."""
    from biffo_plugin_sdk import ForwardedUser

    from idea_scout.models import ModelCatalogEntry

    other_owner = "other-founder-sub"

    core.model_catalog = [
        ModelCatalogEntry(
            id="m1",
            model_id="openai/gpt-4:online",
            label="GPT-4",
            active=True,
            is_default=True,
            web_capable=True,
        ),
    ]

    # First founder creates a run with a model
    resp1 = _start(client, research_model="m1")
    assert resp1.status_code == 201

    # Second founder's request should only see their own runs
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub=other_owner, groups=["founder"], token="tok"
    )
    client2 = TestClient(app)
    app.dependency_overrides[get_service] = lambda: IdeaScoutService(
        core, research_model="research/m", synthesis_model="synthesis/m"
    )

    resp = client2.get("/runs")
    assert resp.status_code == 200
    runs = resp.json()
    # Other founder should have no runs
    assert len(runs) == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/build-types"),
        ("GET", "/complexity-levels"),
        ("GET", "/models"),
        ("GET", "/models/last-used"),
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
