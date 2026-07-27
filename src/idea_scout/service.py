"""Idea Scout's orchestration — transport-agnostic.

Pure async logic over the ``CoreGateway`` port: start a run, fan out to three
research agents, fan back in to one synthesis agent, and materialise its
structured output into stored candidates. No HTTP, no AWS, no LLM SDK.

**Why the state machine advances on poll.** There is no event-subscriber write
path: Core derives the owner from the founder's forwarded token, so every write
must happen inside a founder request (ADR-0017 §5). A founder polling their run
is exactly such a request, so that poll is where research is collected, the
synthesis run is fired, and candidates are stored — the same model the Ideation
Engine uses to materialise its report. The consequence worth knowing: a run only
progresses while someone is looking at it. That is fine for a founder watching a
run they just started, and it is the reason the eventual scheduled/cadence
feature will need a different trigger, not just a cron calling ``start_run``.

**Why a failed research agent doesn't fail the run.** Three angles are
deliberately redundant. Losing one leaves a thinner but still useful shortlist,
and the founder is told which angle was lost. Losing all three, or the synthesis
run, does fail the run — with a reason they can read.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from .definitions import (
    CANDIDATES_TOOL_NAME,
    DEFAULT_INSTRUCTIONS,
    FINDINGS_TOOL_NAME,
    MAX_CANDIDATES,
    MAX_COMPLEXITY,
    MIN_COMPLEXITY,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    CandidateSet,
    FindingSet,
    candidates_tool_schema,
    complexity_label,
    findings_tool_schema,
    research_definition,
    synthesis_definition,
)
from .models import (
    COMPLETE,
    FAILED,
    RESEARCHING,
    SYNTHESISING,
    BuildType,
    Candidate,
    ScoutRun,
    UserProfile,
)
from .ports import CoreGateway


class IdeaScoutError(Exception):
    """Base for orchestration errors the app layer maps to HTTP statuses."""


class RunNotFoundError(IdeaScoutError):
    """No such run for this founder (missing, deleted, or owned by someone else)."""


class UnknownBuildTypeError(IdeaScoutError):
    """The requested build type isn't an active category."""


class InvalidComplexityError(IdeaScoutError):
    """Complexity outside the slider's range."""


class MalformedCandidatesError(IdeaScoutError):
    """The synthesis run finished without a valid structured shortlist.

    Raised by :func:`extract_candidates` and caught by the service, which records
    it as a failed *run* rather than letting it reach the caller. Agent failures
    are deliberately a run state, not an exception: the founder is polling, and a
    502 tells them nothing they can act on, whereas a ``failed`` run carries a
    reason and stays in their sidebar.
    """


def extract_findings(run_messages: list[dict[str, Any]]) -> FindingSet | None:
    """Pull one research agent's findings out of its transcript.

    Returns ``None`` rather than raising when the tool call is missing or
    invalid: one angle returning nothing usable is a degraded run, not a failed
    one, and the caller decides whether enough angles survived.
    """
    data = _tool_call_arguments(run_messages, FINDINGS_TOOL_NAME)
    if data is None:
        return None
    try:
        return FindingSet.model_validate(data)
    except ValidationError:
        return None


def extract_candidates(run_messages: list[dict[str, Any]]) -> CandidateSet:
    """Pull the ranked shortlist out of the synthesis run's transcript.

    Raises :class:`MalformedCandidatesError` if it is missing or invalid — unlike
    the research agents there is no redundancy here, so there is nothing to
    degrade to.
    """
    data = _tool_call_arguments(run_messages, CANDIDATES_TOOL_NAME)
    if data is None:
        raise MalformedCandidatesError(
            f"the synthesis run produced no {CANDIDATES_TOOL_NAME} tool call"
        )
    try:
        return CandidateSet.model_validate(data)
    except ValidationError as exc:
        raise MalformedCandidatesError(str(exc)) from exc


def _tool_call_arguments(messages: list[dict[str, Any]], tool_name: str) -> Any:
    """The parsed arguments of the last call to ``tool_name`` in a transcript, or
    ``None``. Last, not first: if a model retries a malformed tool call, the
    later attempt is the one it meant."""
    found: Any = None
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") != tool_name:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    found = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            else:
                found = arguments
    return found


class IdeaScoutService:
    def __init__(
        self,
        core: CoreGateway,
        *,
        research_model: str,
        synthesis_model: str,
    ) -> None:
        self._core = core
        self._research_model = research_model
        self._synthesis_model = synthesis_model

    # ── Inputs ───────────────────────────────────────────────────────────────

    async def list_build_types(self) -> list[BuildType]:
        return await self._core.list_build_types(active_only=True)

    # ── Starting a run ───────────────────────────────────────────────────────

    async def start_run(self, *, owner_sub: str, build_type: str, complexity: int) -> ScoutRun:
        """Validate the inputs, brief the three research agents, and record the run.

        The build type is validated against the *active* list rather than trusted:
        it arrives from a client, and an inactive or invented category would brief
        agents on something an admin has deliberately withdrawn.
        """
        if not MIN_COMPLEXITY <= complexity <= MAX_COMPLEXITY:
            raise InvalidComplexityError(complexity)

        build_types = await self._core.list_build_types(active_only=True)
        chosen = next((t for t in build_types if t.key == build_type), None)
        if chosen is None:
            raise UnknownBuildTypeError(build_type)

        profile = await self._core.get_user_profile(owner_sub=owner_sub)
        brief = self._build_brief(profile=profile, build_type=chosen, complexity=complexity)

        research_run_ids = []
        for agent_name in RESEARCH_AGENT_NAMES:
            instructions, model = await self._resolve_agent(agent_name, self._research_model)
            run_id = await self._core.request_agent_run(
                agent_name=agent_name,
                definition=research_definition(model=model, instructions=instructions),
                output_tool=findings_tool_schema(),
                input_payload={"brief": brief},
            )
            research_run_ids.append(run_id)

        return await self._core.create_run(
            owner_sub=owner_sub,
            build_type=build_type,
            complexity=complexity,
            profile_snapshot=_profile_payload(profile),
            research_run_ids=research_run_ids,
        )

    # ── Reading a run (and advancing it) ─────────────────────────────────────

    async def get_run(self, *, owner_sub: str, run_id: str) -> ScoutRun:
        """The run's current state, advancing the state machine if the agent runs
        it is waiting on have finished. Safe to call repeatedly — each transition
        is guarded by the stored status, so a second concurrent poll re-reads
        rather than re-firing."""
        run = await self._load_owned(owner_sub=owner_sub, run_id=run_id)
        if run.status == RESEARCHING:
            return await self._advance_research(run)
        if run.status == SYNTHESISING:
            return await self._advance_synthesis(run)
        return run

    async def list_runs(self, *, owner_sub: str) -> list[ScoutRun]:
        """This founder's runs, most-recent-first, excluding soft-deleted ones.

        Deliberately does **not** advance any state machine: this is the sidebar,
        and advancing every listed run would fan out reads across every run a
        founder has ever started, on every page load.
        """
        runs = await self._core.list_runs(owner_sub=owner_sub)
        live = [run for run in runs if not run.deleted]
        return sorted(live, key=lambda r: r.created_at or "", reverse=True)

    async def get_candidates(self, *, owner_sub: str, run_id: str) -> list[Candidate]:
        """This run's candidates — empty while it is still in flight. Advances the
        run first, so a founder polling this endpoint alone still makes progress."""
        run = await self.get_run(owner_sub=owner_sub, run_id=run_id)
        if run.status != COMPLETE:
            return []
        return await self._core.list_candidates(owner_sub=owner_sub, run_id=run_id)

    async def delete_run(self, *, owner_sub: str, run_id: str) -> None:
        """Soft-delete, from any status — including in-flight. The agent runs are
        left alone: they are already paid for, and Core owns their lifecycle."""
        await self._load_owned(owner_sub=owner_sub, run_id=run_id)
        await self._core.update_run(run_id=run_id, deleted=True)

    # ── State transitions ────────────────────────────────────────────────────

    async def _advance_research(self, run: ScoutRun) -> ScoutRun:
        """Research -> synthesis, once every research run is terminal.

        A run Core no longer knows about counts as terminal-and-failed rather
        than pending; otherwise a vanished run leaves the scout waiting forever.
        """
        views = [await self._core.get_agent_run(run_id=rid) for rid in run.research_run_ids]
        if any(view is not None and not view.is_terminal for view in views):
            return run  # still researching

        findings = []
        for view in views:
            if view is None or not view.succeeded:
                continue
            finding_set = extract_findings(view.messages)
            if finding_set is not None:
                findings.append(finding_set.model_dump())

        if not findings:
            return await self._fail(
                run,
                "Every research agent failed to return usable findings. "
                "Nothing was found to build a shortlist from — try running again.",
            )

        instructions, model = await self._resolve_agent(SYNTHESIS_AGENT_NAME, self._synthesis_model)
        synthesis_run_id = await self._core.request_agent_run(
            agent_name=SYNTHESIS_AGENT_NAME,
            definition=synthesis_definition(model=model, instructions=instructions),
            output_tool=candidates_tool_schema(),
            input_payload={
                "profile": run.profile_snapshot,
                "build_type": run.build_type,
                "complexity": complexity_label(run.complexity),
                "findings": findings,
            },
        )
        await self._core.update_run(
            run_id=run.id, status=SYNTHESISING, synthesis_run_id=synthesis_run_id
        )
        return _with(run, status=SYNTHESISING, synthesis_run_id=synthesis_run_id)

    async def _advance_synthesis(self, run: ScoutRun) -> ScoutRun:
        """Synthesis -> complete, storing the ranked candidates."""
        if run.synthesis_run_id is None:  # pragma: no cover — guarded by the caller
            return run
        view = await self._core.get_agent_run(run_id=run.synthesis_run_id)
        if view is not None and not view.is_terminal:
            return run  # still synthesising
        if view is None or not view.succeeded:
            return await self._fail(
                run, "The analysis that ranks and scores the ideas failed. Try running again."
            )

        try:
            candidate_set = extract_candidates(view.messages)
        except MalformedCandidatesError:
            return await self._fail(
                run,
                "The analysis finished but returned nothing usable. Try running again.",
            )

        # Trim rather than reject: an over-long list is the model ignoring its
        # brief, not a broken run, and the ranking means the extras are the ones
        # it rated lowest anyway.
        candidates = [c.model_dump() for c in candidate_set.candidates][:MAX_CANDIDATES]
        if not candidates:
            return await self._fail(
                run, "The analysis returned no ideas at all. Try running again."
            )

        await self._core.save_candidates(run_id=run.id, candidates=candidates, model=view.model)
        await self._core.update_run(run_id=run.id, status=COMPLETE)
        return _with(run, status=COMPLETE)

    async def _fail(self, run: ScoutRun, reason: str) -> ScoutRun:
        await self._core.update_run(run_id=run.id, status=FAILED, failure_reason=reason)
        return _with(run, status=FAILED, failure_reason=reason)

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _load_owned(self, *, owner_sub: str, run_id: str) -> ScoutRun:
        """A run this founder owns and hasn't deleted, or :class:`RunNotFoundError`.

        A soft-deleted run reads as missing rather than as a distinct state: the
        founder removed it, so nothing should resurrect it into their UI.
        """
        run = await self._core.get_run(owner_sub=owner_sub, run_id=run_id)
        if run is None or run.deleted:
            raise RunNotFoundError(run_id)
        return run

    async def _resolve_agent(self, role: str, fallback_model: str) -> tuple[str, str]:
        """The live, admin-editable prompt and model for an agent role, falling
        back to the built-in default when an admin has never configured one."""
        config = await self._core.get_own_config(role=role)
        if config:
            return config["system_prompt"], config["model"]
        return DEFAULT_INSTRUCTIONS[role], fallback_model

    @staticmethod
    def _build_brief(
        *, profile: UserProfile, build_type: BuildType, complexity: int
    ) -> dict[str, Any]:
        """What the agents are told about who this run is for.

        A structured payload rather than a prose paragraph: the prompts already
        say how to weigh it, and prose assembled here would be a second place
        that instruction lives. When the founder has saved no profile the
        ``profile`` key is omitted entirely rather than sent as a shape full of
        nulls, so the model isn't invited to invent a founder to fit it.
        """
        brief: dict[str, Any] = {
            "build_type": {
                "key": build_type.key,
                "label": build_type.label,
                "description": build_type.description,
            },
            "complexity": complexity_label(complexity),
        }
        if not profile.is_empty:
            brief["profile"] = _profile_payload(profile)
        return brief


def _profile_payload(profile: UserProfile) -> dict[str, Any]:
    """The profile as the agents see it, and as it is snapshotted on the run.

    Only the fields that inform an idea: no LinkedIn URL and no ``updated_at``,
    which tell a research agent nothing and would just be more untrusted text in
    the payload.
    """
    return {
        "headline": profile.headline,
        "years_experience": profile.years_experience,
        "founder_before": profile.founder_before,
        "founder_history": profile.founder_history,
        "commitment_level": profile.commitment_level,
        "bio": profile.bio,
        "focus_areas": list(profile.focus_areas),
        "strengths": list(profile.strengths),
    }


def _with(run: ScoutRun, **changes: Any) -> ScoutRun:
    """A copy of the run with fields replaced — so a transition returns the new
    state without a second read of Core."""
    return replace(run, **changes)
