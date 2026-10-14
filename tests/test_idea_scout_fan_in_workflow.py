"""Startup reconcile of the fan-in workflow and agent models: stale -> current,
second startup changes nothing."""

from __future__ import annotations

import asyncio
from typing import Any

from idea_scout import fan_in_workflow as fw
from idea_scout import model_selection as ms
from idea_scout.definitions import ALL_AGENT_NAMES, SYNTHESIS_AGENT_NAME, effective_model


class _Core:
    """In-memory Core: catalog, agent rows and workflow definitions."""

    def __init__(self) -> None:
        self.workflows: list[dict[str, Any]] = [
            {
                "id": "w1",
                "name": fw.WORKFLOW_NAME,
                "trigger_source": "biffo.core",
                "trigger_detail_type": "agent.run.completed",
                "action_type": "agent_fan_in",
                "action_config": {"agent_name": SYNTHESIS_AGENT_NAME, "timeout_seconds": 240},
                "enabled": True,
            }
        ]
        self.writes = 0

    async def request(self, method: str, path: str, json: Any = None) -> Any:
        if method == "GET":
            return [dict(w) for w in self.workflows]
        self.writes += 1
        if method == "PUT":
            self.workflows = [{**json, "id": path.rsplit("/", 1)[1]}]
        else:
            self.workflows.append({**json, "id": "new"})
        return None


class _Backend:
    def __init__(self) -> None:
        self.catalog: list[dict[str, Any]] = [
            {
                "id": "c9",
                "model_id": "moonshotai/kimi-k3:online",
                "label": "k",
                "active": True,
                "is_default": True,
            }
        ]
        self.agents: dict[str, str] = {n: "moonshotai/kimi-k3:online" for n in ALL_AGENT_NAMES}
        self.writes = 0

    async def list_catalog(self):
        return [dict(r) for r in self.catalog]

    async def create_catalog(self, row):
        self.writes += 1
        self.catalog.append({"id": f"n{len(self.catalog)}", "is_default": False, **row})

    async def update_catalog(self, row_id, fields):
        self.writes += 1
        for r in self.catalog:
            if str(r["id"]) == row_id:
                r.update(fields)

    async def get_agent_models(self) -> dict[str, str | None]:
        return dict(self.agents)

    async def seed_agents(self, payloads):
        for p in payloads:
            self.writes += 1
            self.agents[p["agent_key"]] = p["model"]

    async def set_agent_model(self, agent_key, model):
        self.writes += 1
        self.agents[agent_key] = model

    async def get_agent_prompts(self):
        return {}

    async def set_agent_prompt(self, agent_key, prompt):
        self.writes += 1


def test_stale_definition_and_kimi_online_row_end_current_and_second_run_is_a_noop():
    core, backend = _Core(), _Backend()

    async def startup() -> str:
        base = await ms.reconcile(backend)
        await fw.reconcile_workflow(core.request)
        return base

    base = asyncio.run(startup())

    assert core.workflows[0]["action_config"] == fw.definition()["action_config"]
    assert core.workflows[0]["action_config"]["timeout_seconds"] == fw.SYNTHESIS_TIMEOUT_SECONDS
    assert backend.agents == {n: effective_model(base, n) for n in ALL_AGENT_NAMES}
    assert not backend.agents[SYNTHESIS_AGENT_NAME].endswith(":online")

    before = (core.writes, backend.writes)
    asyncio.run(startup())
    assert (core.writes, backend.writes) == before


def test_missing_definition_is_created_once():
    core = _Core()
    core.workflows = []
    assert asyncio.run(fw.reconcile_workflow(core.request)) == "created"
    assert asyncio.run(fw.reconcile_workflow(core.request)) == "unchanged"
    assert core.writes == 1
