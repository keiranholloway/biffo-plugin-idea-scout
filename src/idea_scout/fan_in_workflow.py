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

#: Internal (SigV4) route that upserts this plugin's own workflow definitions.
WORKFLOWS_PATH = "/api/v1/internal/plugins/me/workflows/seed"

DEFINITION_KEY = "idea-scout-fan-in"


def definition() -> dict[str, Any]:
    return {
        "definition_key": DEFINITION_KEY,
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
    """Seed the fan-in definition through Core's idempotent seed route.

    Core upserts by ``definition_key`` (adopting a same-name unowned row), so
    repeating this on every startup converges on the current definition.
    Returns ``"created"``, ``"updated"`` or ``"unchanged"`` from Core's per-row
    result, or ``"seeded"`` when Core reports no detail.
    """
    result = await request("POST", WORKFLOWS_PATH, json=[definition()])
    row = result[0] if isinstance(result, list) and result else None
    if not isinstance(row, dict):
        return "seeded"
    if row.get("created"):
        return "created"
    if row.get("updated"):
        return "updated"
    if "created" in row or "updated" in row:
        return "unchanged"
    return "seeded"
