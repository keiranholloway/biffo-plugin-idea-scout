"""One model for every agent: the helper, the admin routes, and the startup
reconcile. A fake backend records every write."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

from idea_scout import admin_app as admin_module
from idea_scout import model_selection as ms
from idea_scout.definitions import (
    AGENT_WEB_SEARCH,
    ALL_AGENT_NAMES,
    CURATED_MODELS,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_SELECTED_MODEL,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    InvalidBaseModelError,
    effective_model,
)


class FakeBackend:
    def __init__(self, catalog: list[dict[str, Any]], agents: dict[str, str] | None = None):
        self.catalog = catalog
        self.agents = dict(agents or {})
        self.writes: list[tuple[Any, ...]] = []
        self.seeded: list[str] = []
        self.prompts: dict[str, str] = {}

    async def list_catalog(self):
        return [dict(r) for r in self.catalog]

    async def create_catalog(self, row):
        self.writes.append(("create", row["model_id"]))
        self.catalog.append({"id": f"new-{len(self.catalog)}", "is_default": False, **row})

    async def update_catalog(self, row_id, fields):
        self.writes.append(("update", row_id, fields))
        for r in self.catalog:
            if str(r["id"]) == row_id:
                r.update(fields)

    async def get_agent_models(self) -> dict[str, str | None]:
        return dict(self.agents)

    async def seed_agents(self, payloads):
        for p in payloads:
            self.seeded.append(p["agent_key"])
            self.agents[p["agent_key"]] = p["model"]
            self.writes.append(("seed", p["agent_key"], p["model"]))

    async def set_agent_model(self, agent_key, model):
        self.writes.append(("set", agent_key, model))
        self.agents[agent_key] = model

    async def get_agent_prompts(self) -> dict[str, str]:
        return dict(self.prompts)

    async def set_agent_prompt(self, agent_key, prompt):
        self.prompts[agent_key] = prompt


def _row(i: str, model_id: str, *, active=True, default=False) -> dict[str, Any]:
    return {
        "id": i,
        "model_id": model_id,
        "label": model_id,
        "active": active,
        "is_default": default,
    }


# ── the helper ───────────────────────────────────────────────────────────────


def test_helper_adds_online_only_for_research_agents():
    for name in RESEARCH_AGENT_NAMES:
        assert effective_model("x", name) == "x:online"
    for name in ALL_AGENT_NAMES:
        if name not in RESEARCH_AGENT_NAMES:
            assert effective_model("x", name) == "x"
            assert AGENT_WEB_SEARCH[name] is False
    assert len(ALL_AGENT_NAMES) == 7


@pytest.mark.parametrize("bad", ["x:online", "x:free", "", "a:b:c"])
def test_helper_rejects_a_base_id_containing_a_colon(bad):
    with pytest.raises(InvalidBaseModelError):
        effective_model(bad, SYNTHESIS_AGENT_NAME)


def test_curated_list_is_base_ids_and_contains_the_default():
    ids = [m["model_id"] for m in CURATED_MODELS]
    assert DEFAULT_SELECTED_MODEL in ids
    assert len(ids) == 11
    assert all(":" not in i for i in ids)


# ── admin routes ─────────────────────────────────────────────────────────────


@pytest.fixture
def admin(monkeypatch):
    backend = FakeBackend(
        [
            _row("c1", "a/one", default=True),
            _row("c2", "b/two"),
            _row("c3", "c/off", active=False),
            _row("c4", "legacy/x:online"),
        ]
    )
    admin_module.app.dependency_overrides[admin_module.require_admin] = lambda: ForwardedUser(
        sub="adm", groups=["admin"], token="tok"
    )
    monkeypatch.setattr(admin_module, "_admin_backend", lambda _admin: backend)
    yield TestClient(admin_module.app), backend
    admin_module.app.dependency_overrides.clear()


def test_put_model_sets_only_default_and_writes_all_agent_rows(admin):
    client, backend = admin
    backend.agents = {SYNTHESIS_AGENT_NAME: "stale:online"}  # others absent

    resp = client.put("/model", json={"model_id": "b/two"})

    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in backend.catalog if r["is_default"]] == ["c2"]
    assert backend.agents == {n: effective_model("b/two", n) for n in ALL_AGENT_NAMES}
    # absent rows were seeded before writing; the stale row was rewritten
    assert set(backend.seeded) == set(ALL_AGENT_NAMES) - {SYNTHESIS_AGENT_NAME}
    assert ("set", SYNTHESIS_AGENT_NAME, "b/two") in backend.writes
    body = resp.json()
    assert body["selected_model_id"] == "b/two"
    assert not any(a["drift"] for a in body["agents"])


@pytest.mark.parametrize("model_id", ["c/off", "nope/none", "b/two:online", "legacy/x:online"])
def test_put_model_rejects_inactive_unknown_or_colon_ids_and_writes_nothing(admin, model_id):
    client, backend = admin
    resp = client.put("/model", json={"model_id": model_id})
    assert resp.status_code == 422
    assert backend.writes == []


def test_get_model_flags_drift_and_hides_legacy_and_inactive(admin):
    client, backend = admin
    backend.agents = {n: effective_model("a/one", n) for n in ALL_AGENT_NAMES}
    backend.agents[SYNTHESIS_AGENT_NAME] = "a/one:online"

    body = client.get("/model").json()

    assert body["selected_model_id"] == "a/one"
    assert {o["model_id"] for o in body["options"]} == {"a/one", "b/two"}
    by_key = {a["agent_key"]: a for a in body["agents"]}
    assert by_key[SYNTHESIS_AGENT_NAME]["drift"] is True
    assert by_key[SYNTHESIS_AGENT_NAME]["effective_model"] == "a/one"
    assert by_key[SYNTHESIS_AGENT_NAME]["web_search"] is False
    assert by_key[RESEARCH_AGENT_NAMES[0]]["drift"] is False
    assert by_key[RESEARCH_AGENT_NAMES[0]]["web_search"] is True


def test_put_chat_agent_with_a_different_model_is_422(admin, monkeypatch):
    client, _ = admin
    sent: list[Any] = []

    async def fake_core(method, path, *, admin, json=None):
        sent.append((method, path, json))
        return {}

    monkeypatch.setattr(admin_module, "_core_request", fake_core)

    bad = client.put(f"/chat-agents/{SYNTHESIS_AGENT_NAME}", json={"model": "x/y:online"})
    assert bad.status_code == 422
    assert sent == []
    ok = client.put(
        f"/chat-agents/{SYNTHESIS_AGENT_NAME}",
        json={"model": "a/one", "system_prompt": "p"},
    )
    assert ok.status_code == 200
    no_model = client.put(f"/chat-agents/{SYNTHESIS_AGENT_NAME}", json={"system_prompt": "p"})
    assert no_model.status_code == 200


# ── startup ──────────────────────────────────────────────────────────────────


def test_seed_catalog_inserts_only_absent_and_deactivates_legacy():
    backend = FakeBackend(
        [
            _row("c1", "anthropic/claude-sonnet-5.5", default=True),
            _row("c9", "moonshotai/kimi-k3:online", default=True),
        ]
    )
    asyncio.run(ms.seed_catalog(backend))

    created = [w[1] for w in backend.writes if w[0] == "create"]
    assert "anthropic/claude-sonnet-5.5" not in created
    assert len(created) == len(CURATED_MODELS) - 1
    legacy = next(r for r in backend.catalog if r["id"] == "c9")
    assert legacy["active"] is False and legacy["is_default"] is False
    asyncio.run(ms.seed_catalog(backend))
    assert len([w for w in backend.writes if w[0] == "create"]) == len(created)


def test_reconcile_without_a_base_default_selects_sonnet_and_rewrites_every_row():
    backend = FakeBackend(
        [_row("c9", "moonshotai/kimi-k3:online", default=True)],
        agents={n: "hand/entered" for n in ALL_AGENT_NAMES}
        | {SYNTHESIS_AGENT_NAME: "moonshotai/kimi-k3:online"},
    )

    base = asyncio.run(ms.reconcile(backend))

    assert base == "anthropic/claude-sonnet-5.5"
    defaults = [r["model_id"] for r in backend.catalog if r["is_default"] and r["active"]]
    assert defaults == ["anthropic/claude-sonnet-5.5"]
    assert backend.agents == {n: effective_model(base, n) for n in ALL_AGENT_NAMES}


def test_reconcile_keeps_an_existing_base_default():
    backend = FakeBackend([_row("c1", "z-ai/glm-5.3", default=True)])
    assert asyncio.run(ms.reconcile(backend)) == "z-ai/glm-5.3"
    assert backend.agents[RESEARCH_AGENT_NAMES[0]] == "z-ai/glm-5.3:online"


def test_seeded_rows_carry_the_built_in_prompts():
    backend = FakeBackend([_row("c1", "a/one", default=True)])
    asyncio.run(ms.apply_selection(backend, "a/one"))
    assert set(backend.seeded) == set(ALL_AGENT_NAMES)
    assert all(n in DEFAULT_INSTRUCTIONS for n in backend.seeded)


def test_effective_for_agent_is_none_for_an_unknown_agent():
    backend = FakeBackend([_row("c1", "a/one", default=True)])
    assert asyncio.run(ms.effective_for_agent(backend, "not-an-agent")) is None
    assert asyncio.run(ms.effective_for_agent(backend, RESEARCH_AGENT_NAMES[0])) == "a/one:online"


def test_request_backend_skips_agent_rows_the_seed_route_reports_missing():
    class MissingError(Exception):
        pass

    present = ALL_AGENT_NAMES[0]

    async def request(method, path, **_kw):
        if path.endswith(f"/{present}"):
            return {"model": "m"}
        raise MissingError

    backend = ms.RequestBackend(
        request, catalog_path="/c", agents_path="/a", seed_path="/s", not_found=MissingError
    )
    assert asyncio.run(backend.get_agent_models()) == {present: "m"}


# ── stale stored synthesis prompt ────────────────────────────────────────────


class _PromptBackend(FakeBackend):
    def __init__(self, *a, prompt: str, **k):
        super().__init__(*a, **k)
        self.prompts = {SYNTHESIS_AGENT_NAME: prompt}


def _reconcile_with(prompt: str) -> _PromptBackend:
    backend = _PromptBackend(
        [_row("c1", ms.DEFAULT_SELECTED_MODEL, default=True)],
        {n: effective_model(ms.DEFAULT_SELECTED_MODEL, n) for n in ALL_AGENT_NAMES},
        prompt=prompt,
    )
    asyncio.run(ms.reconcile(backend))
    return backend


def test_reconcile_replaces_a_stored_prompt_asking_for_the_full_set():
    stale = "Score each idea ... each 1–5 with a one-paragraph rationale ..."
    backend = _reconcile_with(stale)
    assert backend.prompts[SYNTHESIS_AGENT_NAME] == DEFAULT_INSTRUCTIONS[SYNTHESIS_AGENT_NAME]


def test_reconcile_leaves_a_current_or_edited_prompt_alone():
    edited = DEFAULT_INSTRUCTIONS[SYNTHESIS_AGENT_NAME] + "\nBe brief."
    backend = _reconcile_with(edited)
    assert backend.prompts[SYNTHESIS_AGENT_NAME] == edited
