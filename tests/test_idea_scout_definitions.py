"""Tests for the agent definitions: the promotion contract, the output-tool
wiring, and the prompt invariants that are easy to break by editing prose.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from idea_scout import definitions as d

# The Ideation Engine's Scorecard axes (ideation/src/ideation/definitions.py).
# Copied deliberately — see the module docstring — so this is the assertion that
# keeps the two in step.
IDEATION_SCORECARD_FIELDS = {
    "viability",
    "complexity",
    "economic_moat",
    "market_fit",
    "build_vs_buy",
    "competitors",
    "summary",
}


# ── The promotion contract ───────────────────────────────────────────────────


def test_scorecard_matches_the_ideation_engines_shape():
    """A candidate is promotable into a Challenger/Analyst session because these
    shapes match. If this fails, either restore the shape or change the Ideation
    Engine too — do not just update the constant."""
    assert set(d.Scorecard.model_fields) == IDEATION_SCORECARD_FIELDS


def test_score_axes_are_one_to_five():
    for axis in ("viability", "complexity", "economic_moat", "market_fit"):
        field = d.Scorecard.model_fields[axis]
        assert field.annotation is d.ScoreAxis, axis

    with pytest.raises(ValidationError):
        d.ScoreAxis(score=0, rationale="too low")
    with pytest.raises(ValidationError):
        d.ScoreAxis(score=6, rationale="too high")
    assert d.ScoreAxis(score=3, rationale="fine").score == 3


def test_prose_axes_tolerate_an_over_structured_model_response():
    """The model sometimes returns a dict where the schema says string. Flatten
    it rather than failing a whole run the founder cannot fix."""
    # Built through model_validate, not the constructor: this is how the data
    # actually arrives — a parsed JSON tool call — and the deviation being
    # tolerated is one the static types say cannot happen.
    axis = {"score": 3, "rationale": "r"}
    card = d.Scorecard.model_validate(
        {
            "viability": axis,
            "complexity": axis,
            "economic_moat": axis,
            "market_fit": axis,
            "build_vs_buy": {"build": "hybrid", "text": "assemble the boring parts"},
            "summary": "Solid.",
        }
    )
    assert card.build_vs_buy == "Hybrid — assemble the boring parts"


def test_prose_axes_flatten_an_unrecognised_dict_shape():
    """The fallback branch: an unexpected dict still yields readable prose
    rather than a stringified dict."""
    card = d.Scorecard.model_validate(
        {
            "viability": {"score": 3, "rationale": "r"},
            "complexity": {"score": 3, "rationale": "r"},
            "economic_moat": {"score": 3, "rationale": "r"},
            "market_fit": {"score": 3, "rationale": "r"},
            "build_vs_buy": "Build.",
            "summary": {"verdict": "Promising", "detail": "but the buyer is unclear"},
        }
    )
    assert card.summary == "Promising — but the buyer is unclear"


def test_candidate_pitch_is_what_gets_promoted():
    """The pitch must stand alone — it is the seed idea carried into the
    Ideation Engine, without the rest of the report for context."""
    assert "Ideation Engine" in (d.Candidate.model_fields["pitch"].description or "")


# ── Output tools ─────────────────────────────────────────────────────────────


def test_output_tool_schemas_name_their_models():
    findings = d.findings_tool_schema()
    assert findings["function"]["name"] == d.FINDINGS_TOOL_NAME
    assert findings["function"]["parameters"] == d.FindingSet.model_json_schema()

    candidates = d.candidates_tool_schema()
    assert candidates["function"]["name"] == d.CANDIDATES_TOOL_NAME
    assert candidates["function"]["parameters"] == d.CandidateSet.model_json_schema()


def test_output_tools_are_never_listed_as_registry_tools():
    """`tools` names registry tools only. An output tool listed there fails the
    run as an unknown tool — a whole-run failure, not a degraded answer."""
    research = d.research_definition(model="m", instructions="i")
    synthesis = d.synthesis_definition(model="m", instructions="i")
    for definition in (research, synthesis):
        assert d.FINDINGS_TOOL_NAME not in definition["tools"]
        assert d.CANDIDATES_TOOL_NAME not in definition["tools"]


def test_no_agent_declares_a_registry_tool():
    """Research reaches the web through the ``:online`` model suffix, not a
    registry tool.

    Declaring ``web_search`` here is what broke the first real run: it is gated
    on a Brave credential, and ``resolve_tools`` *drops* a
    registered-but-unconfigured tool with a warning instead of failing. On a
    deployment without the key every research agent ran, found nothing, and the
    run died at synthesis having paid for four model calls. An empty list cannot
    fail that way.
    """
    assert d.research_definition(model="m", instructions="i")["tools"] == []
    assert d.synthesis_definition(model="m", instructions="i")["tools"] == []


def test_research_instructions_do_not_name_a_tool_the_run_does_not_declare():
    """The prompt told the model to "use the web_search tool" while the run
    offered none, so the model replied that it had no such tool instead of
    researching. Prompt and definition have to agree."""
    for role, instructions in d.DEFAULT_INSTRUCTIONS.items():
        if role == d.SYNTHESIS_AGENT_NAME:
            continue
        assert "web_search" not in instructions, role


def test_definitions_carry_the_instructions_they_are_given():
    """The caller resolves the live, admin-editable prompt and passes it in;
    these builders must not silently substitute their own."""
    assert d.research_definition(model="m", instructions="custom")["instructions"] == "custom"
    assert d.synthesis_definition(model="m", instructions="custom")["instructions"] == "custom"


# ── Prompts and roles ────────────────────────────────────────────────────────


def test_three_research_angles_each_have_a_default_prompt():
    assert len(d.RESEARCH_AGENT_NAMES) == 3
    for name in d.RESEARCH_AGENT_NAMES:
        assert d.DEFAULT_INSTRUCTIONS[name].strip()
    assert d.DEFAULT_INSTRUCTIONS[d.SYNTHESIS_AGENT_NAME].strip()


def test_every_agent_role_has_a_default_prompt_and_vice_versa():
    assert set(d.DEFAULT_INSTRUCTIONS) == {*d.RESEARCH_AGENT_NAMES, d.SYNTHESIS_AGENT_NAME}


def test_research_prompts_ask_for_the_findings_tool_and_synthesis_for_candidates():
    for name in d.RESEARCH_AGENT_NAMES:
        assert d.FINDINGS_TOOL_NAME in d.DEFAULT_INSTRUCTIONS[name]
    assert d.CANDIDATES_TOOL_NAME in d.DEFAULT_INSTRUCTIONS[d.SYNTHESIS_AGENT_NAME]


def _flat(text: str) -> str:
    """Collapse the prompt's hard line wrapping, so an assertion about its
    content doesn't depend on where a line happens to break."""
    return " ".join(text.split())


def test_every_prompt_fences_the_founder_supplied_input():
    """Profile text is free text a founder typed — the injection surface. These
    runs assemble their own input rather than going through Core's chat
    fencing (ADR-0016 §7), so each prompt must carry the guard itself."""
    for instructions in d.DEFAULT_INSTRUCTIONS.values():
        assert "never instructions" in _flat(instructions)


def test_research_prompts_require_real_sources():
    for name in d.RESEARCH_AGENT_NAMES:
        assert "Do not invent sources" in _flat(d.DEFAULT_INSTRUCTIONS[name])


def test_synthesis_prompt_states_the_candidate_range():
    instructions = d.DEFAULT_INSTRUCTIONS[d.SYNTHESIS_AGENT_NAME]
    assert str(d.MIN_CANDIDATES) in instructions
    assert str(d.MAX_CANDIDATES) in instructions


def test_agent_names_are_distinct_and_namespaced():
    names = [*d.RESEARCH_AGENT_NAMES, d.SYNTHESIS_AGENT_NAME]
    assert len(set(names)) == len(names)
    assert all(name.startswith("idea-scout-") for name in names)


# ── Complexity ───────────────────────────────────────────────────────────────


def test_every_slider_position_has_a_label():
    for level in range(d.MIN_COMPLEXITY, d.MAX_COMPLEXITY + 1):
        assert d.complexity_label(level).strip()


def test_out_of_range_complexity_falls_back_rather_than_raising():
    """A bad value is the app layer's job to reject; briefing an agent with a
    KeyError traceback helps nobody."""
    assert d.complexity_label(99) == d.COMPLEXITY_LABELS[3]


def test_the_synthesis_prompt_names_the_dedup_key_the_brief_actually_sends():
    """A key in the payload the prompt never mentions is invisible to the model,
    and a prompt naming a key the brief never sends is a lie. #26 was exactly
    that disagreement — the prompt claimed a founder profile it was not being
    given — so the pair is asserted rather than assumed: `_build_brief` writes
    `previously_suggested`, and synthesis has to be told what it means (#49).
    """
    assert "previously_suggested" in d.SYNTHESIS_INSTRUCTIONS
