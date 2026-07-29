"""In-memory fakes, so the whole fan-out/fan-in is testable with no network.

Two of them, at different levels:

- :class:`FakeCoreGateway` implements the ``CoreGateway`` port directly. Agent
  runs are **scriptable**: a test decides when each one becomes terminal and what
  transcript it produced, which is the only way to exercise a state machine whose
  transitions are driven by other systems finishing.
- :class:`FakeTransport` implements the adapter's ``Transport`` seam and records
  every call, so the adapter's URL/body/serialisation mapping can be asserted
  without a gateway in the way.
"""

from __future__ import annotations

import json
from typing import Any

from idea_scout.adapter import CoreNotFoundError
from idea_scout.definitions import SYNTHESIS_AGENT_NAME
from idea_scout.models import (
    RESEARCHING,
    RUN_COMPLETED,
    RUN_FAILED,
    AgentRunView,
    BuildType,
    Candidate,
    ModelCatalogEntry,
    ScoutRun,
    UserProfile,
)

# ── Canned agent output ──────────────────────────────────────────────────────


def findings_message(tool_name: str = "submit_research_findings", *, angle: str = "community"):
    """A transcript carrying one valid findings tool call."""
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(
                            {
                                "angle": angle,
                                "findings": [
                                    {
                                        "signal": f"{angle} signal",
                                        "why_it_matters": "People are working around it manually.",
                                        "sources": [
                                            {"url": "https://example.com/a", "note": "A thread."}
                                        ],
                                    }
                                ],
                            }
                        ),
                    }
                }
            ],
        }
    ]


def _axis(score: int = 4) -> dict[str, Any]:
    return {"score": score, "rationale": "Grounded in the research."}


def candidate_payload(title: str = "An idea") -> dict[str, Any]:
    return {
        "title": title,
        "pitch": f"{title}: a few sentences that stand on their own.",
        "scorecard": {
            "viability": _axis(),
            "complexity": _axis(3),
            "economic_moat": _axis(2),
            "market_fit": _axis(),
            "build_vs_buy": "Build — nothing existing fits.",
            "competitors": [],
            "summary": "Worth a look.",
        },
        "sources": [{"url": "https://example.com/a", "note": "A thread."}],
    }


def candidates_message(count: int = 5, tool_name: str = "submit_idea_candidates"):
    """A transcript carrying one valid candidates tool call."""
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(
                            {
                                "candidates": [
                                    candidate_payload(f"Idea {i + 1}") for i in range(count)
                                ]
                            }
                        ),
                    }
                }
            ],
        }
    ]


# ── The gateway fake ─────────────────────────────────────────────────────────


class FakeAgentRun:
    """A scriptable agent run. Starts pending; a test finishes it."""

    def __init__(self, run_id: str, agent_name: str) -> None:
        self.id = run_id
        self.agent_name = agent_name
        self.status = "pending"
        self.messages: list[dict[str, Any]] = []
        self.model: str | None = "test-model"
        #: None until a runtime claims it — the signal the service uses to tell
        #: "never started" from "started and failed".
        self.started_at: str | None = None
        #: The chain this run belongs to — what makes sibling runs a set.
        self.causation_id: str | None = None

    def complete(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.status = RUN_COMPLETED
        self.started_at = self.started_at or "2026-07-28T00:00:00Z"
        self.messages = messages or []

    def fail(self) -> None:
        """Claimed, ran, and errored — the ordinary failure.

        Sets `started_at`, because a run only reaches `running` by being
        claimed. Without it this fake was indistinguishable from a run nothing
        ever picked up, and the service now tells a founder two different
        things about those cases.
        """
        self.status = RUN_FAILED
        self.started_at = self.started_at or "2026-07-28T00:00:00Z"

    def never_claimed(self) -> None:
        """Failed WITHOUT ever being claimed — what Core's reaper does to a run
        whose `agent.run.requested` was never delivered (biffo-template#786).

        `started_at` stays None; that is the whole signal.
        """
        self.status = RUN_FAILED
        self.started_at = None


class FakeCoreGateway:
    """An in-memory ``CoreGateway``.

    Owner scoping is enforced here the way Core enforces it in production, rather
    than ignored — otherwise a test would pass against a fake that leaks rows
    while the real thing does not, or vice versa.
    """

    def __init__(
        self,
        *,
        profile: UserProfile | None = None,
        build_types: list[BuildType] | None = None,
        configs: dict[str, dict[str, Any]] | None = None,
        model_catalog: list[ModelCatalogEntry] | None = None,
    ) -> None:
        self.profile = profile if profile is not None else UserProfile(headline="Fractional CTO")
        self.build_types = (
            build_types
            if build_types is not None
            else [BuildType(id="bt1", key="micro-saas", label="MicroSaaS", active=True)]
        )
        self.configs = configs or {}
        self.model_catalog = model_catalog or []
        self.runs: dict[str, ScoutRun] = {}
        self.candidates: list[Candidate] = []
        self.agent_runs: dict[str, FakeAgentRun] = {}
        #: Definitions passed to request_agent_run, in order — so a test can
        #: assert what the agents were actually briefed with.
        self.requested: list[dict[str, Any]] = []
        #: Agent run ids the fake should claim Core has never heard of.
        self.vanished_agent_runs: set[str] = set()
        self._next_id = 0

    def _id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    # ── The founder ──────────────────────────────────────────────────────────

    async def get_user_profile(self, *, owner_sub: str) -> UserProfile:
        return self.profile

    # ── Admin-configured inputs ──────────────────────────────────────────────

    async def list_build_types(self, *, active_only: bool = True) -> list[BuildType]:
        types = self.build_types
        if active_only:
            types = [t for t in types if t.active]
        return list(types)

    async def list_model_catalog(self, *, active_only: bool = True) -> list[ModelCatalogEntry]:
        entries = self.model_catalog
        if active_only:
            entries = [e for e in entries if e.active]
        return sorted(entries, key=lambda e: e.label)

    async def get_own_config(self, *, role: str) -> dict[str, Any] | None:
        return self.configs.get(role)

    # ── Runs ─────────────────────────────────────────────────────────────────

    async def create_run(
        self,
        *,
        owner_sub: str,
        build_type: str,
        complexity: int,
        profile_snapshot: dict[str, Any],
        preferences: list[str],
        research_run_ids: list[str],
        chain_id: str,
        research_model: str | None = None,
    ) -> ScoutRun:
        run = ScoutRun(
            id=self._id("run"),
            owner_sub=owner_sub,
            build_type=build_type,
            complexity=complexity,
            chain_id=chain_id,
            status=RESEARCHING,
            research_run_ids=list(research_run_ids),
            profile_snapshot=profile_snapshot,
            preferences=list(preferences),
            created_at=f"2026-07-27T00:00:{len(self.runs):02d}Z",
            research_model=research_model,
        )
        self.runs[run.id] = run
        return run

    async def get_run(self, *, owner_sub: str, run_id: str) -> ScoutRun | None:
        run = self.runs.get(run_id)
        if run is None or run.owner_sub != owner_sub:
            return None
        return run

    async def list_runs(self, *, owner_sub: str) -> list[ScoutRun]:
        return [r for r in self.runs.values() if r.owner_sub == owner_sub]

    async def update_run(self, *, run_id: str, **fields: Any) -> None:
        from dataclasses import replace

        self.runs[run_id] = replace(self.runs[run_id], **fields)

    # ── Agent runs ───────────────────────────────────────────────────────────

    async def request_agent_run(
        self,
        *,
        agent_name: str,
        definition: dict[str, Any],
        output_tool: dict[str, Any],
        input_payload: dict[str, Any],
        causation_id: str,
    ) -> str:
        run = FakeAgentRun(self._id("agent"), agent_name)
        run.causation_id = causation_id
        self.agent_runs[run.id] = run
        self.requested.append(
            {
                "agent_name": agent_name,
                "definition": definition,
                "output_tool": output_tool,
                "input_payload": input_payload,
                "causation_id": causation_id,
            }
        )
        return run.id

    async def find_chain_run(self, *, chain_id: str, agent_name: str) -> AgentRunView | None:
        """Stands in for the orchestration engine having fired a run in this
        chain. Tests call ``engine_fires_synthesis`` to make one appear."""
        for run in self.agent_runs.values():
            if run.causation_id == chain_id and run.agent_name == agent_name:
                return AgentRunView(
                    id=run.id,
                    status=run.status,
                    messages=run.messages,
                    model=run.model,
                    started_at=run.started_at,
                )
        return None

    async def get_agent_run(self, *, run_id: str) -> AgentRunView | None:
        if run_id in self.vanished_agent_runs:
            return None
        run = self.agent_runs.get(run_id)
        if run is None:
            return None
        return AgentRunView(
            id=run.id,
            status=run.status,
            messages=run.messages,
            model=run.model,
            started_at=run.started_at,
        )

    # ── Candidates ───────────────────────────────────────────────────────────

    async def save_candidates(
        self, *, run_id: str, candidates: list[dict[str, Any]], model: str | None
    ) -> None:
        # No owner in the body — Core stamps it from the forwarded token, and the
        # real adapter sends none either. Ownership is therefore reached through
        # the candidate's run, which is what list_candidates enforces below.
        for rank, candidate in enumerate(candidates, start=1):
            self.candidates.append(
                Candidate(
                    id=self._id("cand"),
                    run_id=run_id,
                    rank=rank,
                    title=candidate["title"],
                    pitch=candidate["pitch"],
                    scorecard=candidate.get("scorecard"),
                    sources=candidate.get("sources") or [],
                    model=model,
                )
            )

    async def list_owner_candidates(self, *, owner_sub: str) -> list[Candidate]:
        # Ownership is reached through the candidate's run, which is what the
        # real owner-data route enforces from the forwarded token.
        owned = {r.id for r in self.runs.values() if r.owner_sub == owner_sub}
        return [c for c in self.candidates if c.run_id in owned]

    async def list_candidates(self, *, owner_sub: str, run_id: str) -> list[Candidate]:
        run = self.runs.get(run_id)
        if run is None or run.owner_sub != owner_sub:
            return []
        return sorted((c for c in self.candidates if c.run_id == run_id), key=lambda c: c.rank)

    # ── Test helpers ─────────────────────────────────────────────────────────

    def research_runs_for(self, run_id: str) -> list[FakeAgentRun]:
        return [self.agent_runs[rid] for rid in self.runs[run_id].research_run_ids]

    def complete_all_research(self, run_id: str) -> None:
        for agent_run in self.research_runs_for(run_id):
            agent_run.complete(findings_message(angle=agent_run.agent_name))

    def engine_fires_synthesis(self, run_id: str) -> FakeAgentRun:
        """What the orchestration engine does when the research set completes:
        create a synthesis run in the same chain. The plugin does not do this —
        it only discovers the result — so tests must not either."""
        scout_run = self.runs[run_id]
        agent_run = FakeAgentRun(self._id("agent"), SYNTHESIS_AGENT_NAME)
        agent_run.causation_id = scout_run.chain_id
        self.agent_runs[agent_run.id] = agent_run
        return agent_run

    def synthesis_run_for(self, run_id: str) -> FakeAgentRun:
        synthesis_run_id = self.runs[run_id].synthesis_run_id
        assert synthesis_run_id is not None, "no synthesis run has been requested yet"
        return self.agent_runs[synthesis_run_id]


# ── The transport fake ───────────────────────────────────────────────────────


class FakeTransport:
    """Records calls and returns canned responses, keyed by ``(method, path)``.

    A missing key returns ``{}`` rather than raising, so a test only has to script
    the calls it cares about — except for paths registered in ``not_found``, which
    raise :class:`CoreNotFoundError` the way Core's 404 does.
    """

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self.responses = responses or {}
        self.not_found: set[tuple[str, str]] = set()
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append({"method": method, "path": path, "json": json, "params": params})
        if (method, path) in self.not_found:
            raise CoreNotFoundError(f"{method} {path} -> 404")
        return self.responses.get((method, path), {})

    def last(self, method: str, path: str) -> dict[str, Any]:
        for call in reversed(self.calls):
            if call["method"] == method and call["path"] == path:
                return call
        raise AssertionError(f"no {method} {path} call was made; got {self.calls}")
