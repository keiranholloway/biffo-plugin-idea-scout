"""Tests for the admin app's builtin-agents endpoint."""

from fastapi.testclient import TestClient

from idea_scout.admin_app import app
from idea_scout.definitions import (
    COMMUNITY_AGENT_NAME,
    COMPETITIVE_AGENT_NAME,
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NARRATIVE_AGENT_NAME,
    SYNTHESIS_AGENT_NAME,
)


def test_builtin_agents_endpoint_exists():
    """The endpoint should respond with built-in agent data."""
    client = TestClient(app)
    response = client.get("/api/v1/admin/plugins/idea-scout/builtin-agents")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert len(data["agents"]) == 4


def test_builtin_agents_research_models_have_online_suffix():
    """Research agents must have the :online suffix to access web search.

    Without :online, research agents silently fail after burning paid calls.
    This test ensures the endpoint returns models with web capability.
    """
    client = TestClient(app)
    response = client.get("/api/v1/admin/plugins/idea-scout/builtin-agents")
    data = response.json()

    research_agents = [
        a
        for a in data["agents"]
        if a["agent_key"] in [COMMUNITY_AGENT_NAME, NARRATIVE_AGENT_NAME, COMPETITIVE_AGENT_NAME]
    ]

    for agent in research_agents:
        assert agent["model"].endswith(":online"), (
            f"Research agent {agent['agent_key']} must have :online suffix. Got: {agent['model']}"
        )


def test_builtin_agents_models_match_constants():
    """Built-in agent models must match the constants in definitions.py.

    Ensures the endpoint, app.py, and seed_agent_config.py all use the same
    defaults so they cannot drift apart.
    """
    client = TestClient(app)
    response = client.get("/api/v1/admin/plugins/idea-scout/builtin-agents")
    data = response.json()

    agents_by_key = {a["agent_key"]: a for a in data["agents"]}

    # Research agents
    for research_key in [COMMUNITY_AGENT_NAME, NARRATIVE_AGENT_NAME, COMPETITIVE_AGENT_NAME]:
        assert agents_by_key[research_key]["model"] == DEFAULT_RESEARCH_MODEL, (
            f"Research agent {research_key} should use DEFAULT_RESEARCH_MODEL. "
            f"Expected: {DEFAULT_RESEARCH_MODEL}, Got: {agents_by_key[research_key]['model']}"
        )

    # Synthesis agent
    assert agents_by_key[SYNTHESIS_AGENT_NAME]["model"] == DEFAULT_SYNTHESIS_MODEL, (
        f"Synthesis agent should use DEFAULT_SYNTHESIS_MODEL. "
        f"Expected: {DEFAULT_SYNTHESIS_MODEL}, Got: {agents_by_key[SYNTHESIS_AGENT_NAME]['model']}"
    )


def test_builtin_agents_have_real_prompts():
    """Built-in agents should return real prompt text, not placeholders."""
    client = TestClient(app)
    response = client.get("/api/v1/admin/plugins/idea-scout/builtin-agents")
    data = response.json()

    for agent in data["agents"]:
        # Real prompts are several sentences; placeholders are not
        assert len(agent["system_prompt"]) > 50, (
            f"Agent {agent['agent_key']} prompt is too short. "
            f"Likely a placeholder: {agent['system_prompt'][:50]}"
        )
        # No placeholder strings
        assert "Built-in prompt — stored row not found" not in agent["system_prompt"]
        assert "(Built-in default)" not in agent["system_prompt"]
