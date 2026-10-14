"""Startup reconcile of the plugin's own ``agent_fan_in`` workflow definition.

Core's workflow row is state a plugin deploy never replaces, so a hand-run seed
script left stale definitions (old single-call ranking, 240s timeout) live on
dev. The plugin now brings that row up to date itself, idempotently.
"""

from __future__ import annotations

from typing import Any

from idea_scout.definitions import (
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    SYNTHESIS_MAX_TURNS,
    candidates_tool_schema,
)

SYNTHESIS_TIMEOUT_SECONDS = 240

WORKFLOW_NAME = "Idea Scout — synthesise once research completes"

#: Internal (SigV4) route for this plugin's own workflow definitions. Core must
#: expose it; see the out-of-scope blocker raised with this change.
WORKFLOWS_PATH = "/api/v1/internal/plugins/me/workflows"

_COMPARED = (
    "name",
    "trigger_source",
    "trigger_detail_type",
    "action_type",
    "action_config",
    "enabled",
)


def definition() -> dict[str, Any]:
    return {
        "name": WORKFLOW_NAME,
        "trigger_source": "biffo.core",
        "trigger_detail_type": "agent.run.completed",
        "action_type": "agent_fan_in",
        "action_config": {
            "expect_agents": ",".join(RESEARCH_AGENT_NAMES),
            "agent_name": SYNTHESIS_AGENT_NAME,
            "max_turns": SYNTHESIS_MAX_TURNS,
            "output_tools": [candidates_tool_schema()],
            "timeout_seconds": SYNTHESIS_TIMEOUT_SECONDS,
        },
        "enabled": True,
    }


async def reconcile_workflow(request: Any) -> str:
    """Create or replace the fan-in definition; no write when it is current.

    Returns ``"created"``, ``"updated"`` or ``"unchanged"``.
    """
    want = definition()
    rows = await request("GET", WORKFLOWS_PATH) or []
    have = next((r for r in rows if r.get("name") == WORKFLOW_NAME), None)
    if have is None:
        await request("POST", WORKFLOWS_PATH, json=want)
        return "created"
    if all(have.get(k) == want[k] for k in _COMPARED):
        return "unchanged"
    await request("PUT", f"{WORKFLOWS_PATH}/{have['id']}", json=want)
    return "updated"
