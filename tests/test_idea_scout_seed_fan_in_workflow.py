"""The workflow definition this plugin cannot run without.

Without it a scout never leaves `researching`: the three research agents run,
bill, and nothing reconciles them. That failure is silent, so the contents of
this definition are asserted rather than trusted.
"""

from __future__ import annotations

from _scripts import load_script

from idea_scout.definitions import (
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    SYNTHESIS_INSTRUCTIONS,
)

_seed = load_script("seed_fan_in_workflow")
WORKFLOW_NAME = _seed.WORKFLOW_NAME
definition = _seed.definition


def test_it_waits_for_exactly_the_agents_the_plugin_requests():
    """The names in expect_agents and the names start_run actually fires must be
    the same set. A drift here is a run that hangs forever."""
    config = definition(model="m")["action_config"]

    assert config["expect_agents"].split(",") == list(RESEARCH_AGENT_NAMES)


def test_it_fires_the_synthesis_agent_the_plugin_looks_for():
    """The plugin discovers the engine's run by agent name — these must match."""
    config = definition(model="m")["action_config"]

    assert config["agent_name"] == SYNTHESIS_AGENT_NAME


def test_it_carries_the_synthesis_prompt():
    assert definition(model="m")["action_config"]["instructions"] == SYNTHESIS_INSTRUCTIONS


def test_it_triggers_on_agent_completions():
    payload = definition(model="m")

    assert payload["trigger_source"] == "biffo.core"
    assert payload["trigger_detail_type"] == "agent.run.completed"
    assert payload["action_type"] == "agent_fan_in"


def test_it_is_enabled_and_named_stably():
    """The name is the idempotency key the seeder matches on — changing it would
    seed a duplicate rather than replace."""
    payload = definition(model="m")

    assert payload["enabled"] is True
    assert payload["name"] == WORKFLOW_NAME


def test_the_model_is_configurable():
    assert definition(model="a/custom-model")["action_config"]["model"] == "a/custom-model"
