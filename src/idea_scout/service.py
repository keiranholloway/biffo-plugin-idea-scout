"""Idea Scout's orchestration — transport-agnostic.

Pure async logic over the ``CoreGateway`` port: start a run, fan out to three
research agents, fan back in to one synthesis agent, and materialise its
structured output into stored candidates. No HTTP, no AWS, no LLM SDK.

**The pipeline runs unattended; only the projection is lazy.** ``start_run``
fires three research agents under one causation chain, and the orchestration
engine's ``agent_fan_in`` fires the synthesis agent when that set completes —
without this plugin being involved, so a founder can close the tab. What still
happens on the founder's read is turning the finished synthesis run into stored
candidate *rows*: Core derives the owner from the forwarded token, so an
owner-scoped write must happen inside a founder request (ADR-0017 §5). By the
time they look, the expensive work is already done and the write is instant.

So this service no longer sequences the pipeline — it correlates the fan-out at
the start, and reads the result at the end. The middle belongs to the engine.

**Why a failed research agent doesn't fail the run.** Three angles are
deliberately redundant. Losing one leaves a thinner but still useful shortlist,
and the founder is told which angle was lost. Losing all three, or the synthesis
run, does fail the run — with a reason they can read.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from .definitions import (
    CANDIDATES_TOOL_NAME,
    DEFAULT_CADENCE_DAYS,
    FINDINGS_TOOL_NAME,
    MAX_CADENCE_DAYS,
    MAX_CANDIDATES,
    MAX_COMPLEXITY,
    MAX_PREVIOUSLY_SUGGESTED,
    MIN_CADENCE_DAYS,
    MIN_COMPLEXITY,
    PREFERENCE_KEYS,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    CandidateSet,
    FindingSet,
    complexity_label,
    findings_tool_schema,
    preference_brief,
    research_definition,
)
from .models import (
    COMPLETE,
    FAILED,
    IN_FLIGHT_STATUSES,
    RESEARCHING,
    SYNTHESISING,
    BuildType,
    BusinessModel,
    CadencePreference,
    CadenceState,
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


class UnknownBusinessModelError(IdeaScoutError):
    """The requested business model isn't an active category.

    Rejected loudly rather than dropped, for the same reason an unknown
    preference key is (#34): a client sending a stale key should learn it is
    stale, not silently get a run scoped to nothing.
    """


class InvalidComplexityError(IdeaScoutError):
    """Complexity outside the slider's range."""


class UnknownPreferenceError(IdeaScoutError):
    """One or more preference keys are not in the known set (#34).

    Loud rather than silent: the prompts weigh preferences by meaning, so a key
    they do not recognise cannot be honoured. A client sending a stale key should
    learn that, not receive a run that quietly ignored half its input.
    """

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__(f"Unknown preference key(s): {', '.join(sorted(keys))}")


class UnknownModelError(IdeaScoutError):
    """The requested research model is not available.

    A model may be unknown (not in the catalog), inactive (withdrawn by admin),
    or not web-capable (missing the :online suffix for research agents).
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"Research model not available: {model_id}")


class InvalidCadenceError(IdeaScoutError):
    """The requested auto-scout interval is outside the allowed range (#50).

    Loud rather than clamped. A founder who asks for a scout every 500 days and
    silently gets 90 has been told nothing, and a client sending 0 — which would
    make every page load "due" and start a run — must learn that it is refused
    rather than have it quietly reinterpreted.
    """

    def __init__(self, cadence_days: int) -> None:
        self.cadence_days = cadence_days
        super().__init__(
            f"Cadence must be between {MIN_CADENCE_DAYS} and {MAX_CADENCE_DAYS} "
            f"days; got {cadence_days}."
        )


class MalformedCandidatesError(IdeaScoutError):
    """The synthesis run finished without a valid structured shortlist.

    Raised by :func:`extract_candidates` and caught by the service, which records
    it as a failed *run* rather than letting it reach the caller. Agent failures
    are deliberately a run state, not an exception: the founder is polling, and a
    502 tells them nothing they can act on, whereas a ``failed`` run carries a
    reason and stays in their sidebar.
    """


class AgentConfigMissingError(IdeaScoutError):
    """An agent role has no configured row and seeding has not run.

    The plugin guarantees rows exist at startup via seeding; a missing row at
    runtime means startup seeding failed or was skipped, and the fallback is
    deliberately removed so the operator knows immediately.
    """

    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(
            f"Agent role '{role}' has no configured row. "
            "Seeding may not have run at startup, or Core was unavailable. "
            "Check the app logs and restart the plugin."
        )


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

    async def list_business_models(self) -> list[BusinessModel]:
        return await self._core.list_business_models(active_only=True)

    async def list_model_catalog(self) -> list:  # type: ignore
        """Admin-configured models for research agents, filtered to active and web-capable."""
        entries = await self._core.list_model_catalog(active_only=True)
        # Only return models that are web-capable, since research agents require web search
        return [e for e in entries if e.web_capable]

    # ── Starting a run ───────────────────────────────────────────────────────

    async def start_run(
        self,
        *,
        owner_sub: str,
        build_type: str,
        complexity: int,
        preferences: list[str] | None = None,
        research_model: str | None = None,
        business_model: str | None = None,
    ) -> ScoutRun:
        """Validate the inputs, brief the three research agents, and record the run.

        The build type is validated against the *active* list rather than trusted:
        it arrives from a client, and an inactive or invented category would brief
        agents on something an admin has deliberately withdrawn.

        ``preferences`` are validated the same way and for the same reason — an
        invented key would reach the prompts, which weigh preferences by meaning
        and have nothing to say about one they do not know. Rejected loudly
        rather than dropped, so a client sending a stale key learns it is stale
        instead of silently getting an unweighted run (#34).

        An empty selection is valid and means "no preferences expressed". It is
        deliberately not defaulted to anything: a default that silently shapes
        results is the invisible-input failure this plugin has already had twice
        (#26, #29).
        """
        if not MIN_COMPLEXITY <= complexity <= MAX_COMPLEXITY:
            raise InvalidComplexityError(complexity)

        chosen_preferences = list(preferences or [])
        unknown = [k for k in chosen_preferences if k not in PREFERENCE_KEYS]
        if unknown:
            raise UnknownPreferenceError(unknown)

        build_types = await self._core.list_build_types(active_only=True)
        chosen = next((t for t in build_types if t.key == build_type), None)
        if chosen is None:
            raise UnknownBuildTypeError(build_type)

        # Optional, unlike the build type: None means "no preference", which is a
        # real answer. Only a *supplied* key is validated — and validated against
        # the active list for the same reason the build type is, since an
        # inactive or invented category would brief agents on something an admin
        # has withdrawn.
        chosen_business_model: BusinessModel | None = None
        if business_model is not None:
            models = await self._core.list_business_models(active_only=True)
            chosen_business_model = next((m for m in models if m.key == business_model), None)
            if chosen_business_model is None:
                raise UnknownBusinessModelError(business_model)

        # Validate and resolve research_model if provided. Must be present, active,
        # and web-capable. Resolve once here to the model slug, then pass it down
        # so we don't re-fetch the catalog for each research agent.
        chosen_model_slug: str | None = None
        if research_model is not None:
            catalog = await self._core.list_model_catalog(active_only=False)
            model_entry = next((e for e in catalog if e.id == research_model), None)
            if model_entry is None or not model_entry.active or not model_entry.web_capable:
                raise UnknownModelError(research_model)
            chosen_model_slug = model_entry.model_id

        profile = await self._core.get_user_profile(owner_sub=owner_sub)
        previously_suggested = await self._previously_suggested(owner_sub=owner_sub)
        brief = self._build_brief(
            profile=profile,
            build_type=chosen,
            complexity=complexity,
            preferences=chosen_preferences,
            previously_suggested=previously_suggested,
            business_model=chosen_business_model,
        )

        # One chain for all three, generated here because the run row does not
        # exist yet — and because this is what makes them a *set* the engine's
        # fan-in can recognise. Three uncorrelated runs would each be a chain
        # root and the join would never fire.
        chain_id = str(uuid.uuid4())

        research_run_ids = []
        for agent_name in RESEARCH_AGENT_NAMES:
            instructions, model = await self._resolve_agent(
                agent_name, self._research_model, chosen_model_slug=chosen_model_slug
            )
            run_id = await self._core.request_agent_run(
                agent_name=agent_name,
                definition=research_definition(model=model, instructions=instructions),
                output_tool=findings_tool_schema(),
                input_payload={"brief": brief},
                causation_id=chain_id,
            )
            research_run_ids.append(run_id)

        return await self._core.create_run(
            owner_sub=owner_sub,
            build_type=build_type,
            complexity=complexity,
            profile_snapshot=_profile_payload(profile),
            preferences=chosen_preferences,
            research_run_ids=research_run_ids,
            chain_id=chain_id,
            business_model=business_model,
            research_model=chosen_model_slug,
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

    # ── Cadence (#50) ────────────────────────────────────────────────────────

    async def get_cadence(self, *, owner_sub: str) -> CadencePreference:
        """This founder's cadence preference, or the built-in default.

        **No stored row is not "off".** A founder who has never opened the
        control gets ``enabled=True`` at :data:`DEFAULT_CADENCE_DAYS`, which is
        precisely what the hardcoded constant this replaces did — so shipping
        the preference changes nothing for anyone who does not use it. Only a
        stored row with ``enabled`` false suppresses the auto-start.
        """
        stored = await self._core.get_cadence(owner_sub=owner_sub)
        if stored is None:
            return CadencePreference(enabled=True, cadence_days=DEFAULT_CADENCE_DAYS)
        return stored

    async def set_cadence(
        self, *, owner_sub: str, enabled: bool, cadence_days: int
    ) -> CadencePreference:
        """Save this founder's cadence preference, inserting or patching.

        Core's owner-data routes have no upsert, so "one row per founder" is
        maintained here: read, then POST if there is nothing and PATCH if there
        is. Racing two saves could in principle leave two rows, which is why
        the read side takes the first deterministically rather than raising —
        a founder must never be locked out of their own settings.

        ``cadence_days`` is validated **even when ``enabled`` is false**,
        because it is remembered across an off/on toggle: an out-of-range value
        accepted while off would come back the moment they switch on.

        Validated here and not only in the route model, for the same reason
        complexity is: this is the layer that owns the rule, and a second
        caller must not be able to route around it.
        """
        if not MIN_CADENCE_DAYS <= cadence_days <= MAX_CADENCE_DAYS:
            raise InvalidCadenceError(cadence_days)

        stored = await self._core.get_cadence(owner_sub=owner_sub)
        if stored is None or stored.id is None:
            return await self._core.create_cadence(
                owner_sub=owner_sub, enabled=enabled, cadence_days=cadence_days
            )
        return await self._core.update_cadence(
            cadence_id=stored.id, enabled=enabled, cadence_days=cadence_days
        )

    async def cadence_state(self, *, owner_sub: str, now: datetime | None = None) -> CadenceState:
        """The preference plus when the next scout is due and whether it is due
        **now** — the single authority on the auto-start.

        This is the "derive it" half of the feature. ``next_due_at`` is computed
        from the stored interval and the most recent run's ``created_at`` on
        every read; nothing writes it down, so there is no second copy to fall
        out of step with the preference the founder just changed. The frontend
        reads ``is_due`` rather than recomputing staleness against a constant of
        its own — that duplicate is what this change removes.
        """
        preference = await self.get_cadence(owner_sub=owner_sub)
        # Most-recent-first and soft-deleted rows already excluded, so [0] is
        # the run to measure from. A deleted run must not hold the cadence
        # open: the founder removed it, and it is no longer their last scout.
        runs = await self.list_runs(owner_sub=owner_sub)
        return _derive_cadence_state(
            preference=preference,
            most_recent=runs[0] if runs else None,
            now=now if now is not None else datetime.now(UTC),
        )

    # ── State transitions ────────────────────────────────────────────────────

    async def _advance_research(self, run: ScoutRun) -> ScoutRun:
        """Research -> synthesis, when the engine has fired the synthesis run.

        This no longer *decides* anything: the orchestration engine watches the
        research set and fires synthesis itself (``agent_fan_in``). All this does
        is discover the run the engine created — nothing tells the plugin its id
        — and record it so subsequent polls can read its output.

        A research set that failed outright never produces a synthesis run, so
        the run would otherwise sit in ``researching`` forever. That case is
        detected here: every research run terminal, none successful.
        """
        synthesis = await self._core.find_chain_run(
            chain_id=run.chain_id, agent_name=SYNTHESIS_AGENT_NAME
        )
        if synthesis is not None:
            await self._core.update_run(
                run_id=run.id, status=SYNTHESISING, synthesis_run_id=synthesis.id
            )
            return _with(run, status=SYNTHESISING, synthesis_run_id=synthesis.id)

        # No synthesis run yet. Either the research is still going — the normal
        # case, and nothing to do — or it finished with nothing usable, in which
        # case the engine correctly declined to fire and this run must not hang.
        views = [await self._core.get_agent_run(run_id=rid) for rid in run.research_run_ids]
        if any(view is not None and not view.is_terminal for view in views):
            return run  # still researching
        if any(view is not None and view.succeeded for view in views):
            # Terminal and at least one succeeded: the engine is entitled to a
            # moment to react to the completion event. Stay put rather than
            # racing it to a false failure.
            return run
        if views and all(v is not None and v.never_started for v in views):
            # None of them was ever claimed — the same delivery fault, one stage
            # earlier. "Failed to return usable findings" would imply they ran.
            return await self._fail(run, self.NEVER_STARTED_REASON)
        return await self._fail(
            run,
            "Every research agent failed to return usable findings. "
            "Nothing was found to build a shortlist from — try running again.",
        )

    async def _advance_synthesis(self, run: ScoutRun) -> ScoutRun:
        """Synthesis -> complete, storing the ranked candidates."""
        if run.synthesis_run_id is None:  # pragma: no cover — guarded by the caller
            return run
        view = await self._core.get_agent_run(run_id=run.synthesis_run_id)
        if view is not None and not view.is_terminal:
            return run  # still synthesising
        if view is not None and view.never_started:
            # Reaped as unclaimed. Saying "the analysis failed" here would be
            # false — it never ran — and sends the reader to look at the model
            # or the prompt instead of at event delivery.
            return await self._fail(run, self.NEVER_STARTED_REASON)
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

    #: Shown when an agent run was never claimed by a runtime rather than having
    #: run and gone wrong. The distinction matters to a founder: "it broke" invites
    #: a retry of the same thing, "it never started" is an infrastructure problem
    #: they cannot fix by retrying — though retrying IS the right move, because the
    #: delivery failure is intermittent (biffo-platform#96).
    NEVER_STARTED_REASON = (
        "This scout never started — the work was queued but nothing picked it up, "
        "so no research ran and nothing was charged for it. This is a fault on our "
        "side, not with what you asked for. Running it again usually works."
    )

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

    async def _resolve_agent(
        self, role: str, fallback_model: str, chosen_model_slug: str | None = None
    ) -> tuple[str, str]:
        """The live, admin-editable prompt and model for an agent role.

        Rows are guaranteed to exist at startup via seeding, so a missing row
        raises loudly rather than silently falling back to built-in defaults.

        For research agents only, the founder's chosen_model_slug (already
        resolved to the actual model id) overrides the stored model. Synthesis
        always uses the stored model, never the founder's choice.
        """
        config = await self._core.get_own_config(role=role)
        if config is None:
            raise AgentConfigMissingError(role)

        instructions, model = config["system_prompt"], config["model"]

        # For research agents, founder's choice overrides the resolved model
        if chosen_model_slug and role in RESEARCH_AGENT_NAMES:
            model = chosen_model_slug

        return instructions, model

    async def _previously_suggested(self, *, owner_sub: str) -> list[str]:
        """Titles this founder has already been shown, newest first (#49).

        Ordered by the *run's* timestamp rather than the candidate's: a run's
        candidates are all written together, so the run is the unit that has a
        meaningful recency, and it is the field both the real route and the
        fake actually carry.

        Deduplicated case-insensitively — the same idea surfacing twice under
        the same words should occupy one slot of the budget, not two — and
        capped, because an unbounded history eventually crowds out the brief it
        is attached to.
        """
        runs = await self._core.list_runs(owner_sub=owner_sub)
        recency = {r.id: (r.created_at or "") for r in runs}
        candidates = await self._core.list_owner_candidates(owner_sub=owner_sub)
        ordered = sorted(
            candidates,
            key=lambda c: (recency.get(c.run_id, ""), -c.rank),
            reverse=True,
        )

        seen: set[str] = set()
        titles: list[str] = []
        for candidate in ordered:
            key = candidate.title.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            titles.append(candidate.title)
            if len(titles) == MAX_PREVIOUSLY_SUGGESTED:
                break
        return titles

    @staticmethod
    def _build_brief(
        *,
        profile: UserProfile,
        build_type: BuildType,
        complexity: int,
        preferences: list[str],
        previously_suggested: list[str] | None = None,
        business_model: BusinessModel | None = None,
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
        # Omitted entirely when the founder expressed no preference, for the same
        # reason an empty profile is: a null here would invite the model to reason
        # about a revenue model that was never chosen.
        if business_model is not None:
            brief["business_model"] = {
                "key": business_model.key,
                "label": business_model.label,
                "description": business_model.description,
            }
        if not profile.is_empty:
            brief["profile"] = _profile_payload(profile)
        # Omitted entirely when nothing was chosen, for the same reason an empty
        # profile is omitted: an empty list invites the model to reason about a
        # preference set that does not exist.
        if preferences:
            brief["preferences"] = preference_brief(preferences)
        # Omitted when the founder has no history, for the same reason as an
        # empty profile: an empty list invites the model to reason about a set
        # that does not exist. Present, it means "you have already offered
        # these — find different ground" (#49).
        if previously_suggested:
            brief["previously_suggested"] = list(previously_suggested)
        return brief


def _parse_timestamp(value: str | None) -> datetime | None:
    """Core's ``created_at`` as an aware datetime, or ``None`` if unreadable.

    Tolerates the trailing ``Z`` form (``fromisoformat`` accepts it on 3.11+,
    but the fakes and older rows are not guaranteed to be uniform) and assumes
    UTC for a naive value, because every timestamp Core stamps is UTC.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _derive_cadence_state(
    *,
    preference: CadencePreference,
    most_recent: ScoutRun | None,
    now: datetime,
) -> CadenceState:
    """Turn a stored preference plus the founder's latest run into a decision.

    Pure, and separated from the reads so every branch below is testable without
    a gateway. The branches, and why each is what it is:

    - **Off** — nothing is ever due. This is the OFF state doing real work: it
      suppresses the auto-start at the only place that decides it, rather than
      hiding a control while the run still fires.
    - **No runs at all** — nothing is due. A founder who has never scouted is
      not "returning to a stale one"; they are new, and there is nothing to
      replay anyway.
    - **The latest run is in flight** — nothing is due, because a scout is
      already running. This is the idempotency guard, and it is read from
      server truth on every request, so a refresh or a second tab moments after
      an auto-start sees the same fact and does not fire again.
    - **An unreadable timestamp** — due. Core always stamps ``created_at``, so
      this can only be a malformed value; treating it as "we do not know, so
      act as if it is old" costs at most one extra run, where treating it as
      fresh would silently never offer that founder a scout again.
    """
    off = CadenceState(
        enabled=preference.enabled,
        cadence_days=preference.cadence_days,
        next_due_at=None,
        is_due=False,
    )
    if not preference.enabled or most_recent is None:
        return off

    in_flight = most_recent.status in IN_FLIGHT_STATUSES
    started = _parse_timestamp(most_recent.created_at)
    if started is None:
        return replace(off, is_due=not in_flight)

    due_at = started + timedelta(days=preference.cadence_days)
    return replace(
        off,
        next_due_at=due_at.isoformat(),
        is_due=not in_flight and now >= due_at,
    )


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
