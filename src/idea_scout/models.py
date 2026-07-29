"""Plain data types the orchestration works in — no I/O, no framework."""

from __future__ import annotations

from dataclasses import dataclass, field

# Run lifecycle. A run fans out to three research agents, waits for all of them,
# then fans in to one synthesis agent — so "in flight" has two distinct phases
# and the UI says which one it is watching.
RESEARCHING = "researching"  # the parallel research runs are in flight
SYNTHESISING = "synthesising"  # research is in, the ranking/scoring run is in flight
COMPLETE = "complete"  # candidates are stored and readable
FAILED = "failed"  # nothing usable came back; failure_reason says why
STATUSES = frozenset({RESEARCHING, SYNTHESISING, COMPLETE, FAILED})
IN_FLIGHT_STATUSES = frozenset({RESEARCHING, SYNTHESISING})

# Terminal states of an agent run (Core's AgentRun, ADR-0014). Read when a
# founder polls: terminal research runs advance the fan-in, a terminal synthesis
# run is materialised into candidates.
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_TERMINAL = frozenset({RUN_COMPLETED, RUN_FAILED})


@dataclass(frozen=True)
class UserProfile:
    """The founder's profile as Core's internal read returns it. Every field is
    optional: a founder who has saved nothing still gets a run, just a less
    targeted one."""

    headline: str | None = None
    years_experience: int | None = None
    founder_before: bool = False
    founder_history: str | None = None
    commitment_level: str | None = None
    bio: str | None = None
    focus_areas: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when there is nothing here worth briefing an agent with. The
        service still runs — it just cannot personalise, and says so."""
        return not any(
            (
                self.headline,
                self.years_experience,
                self.founder_history,
                self.commitment_level,
                self.bio,
                self.focus_areas,
                self.strengths,
            )
        )


@dataclass(frozen=True)
class BuildType:
    """An admin-configured build-type category, as offered in the run form."""

    id: str
    key: str
    label: str
    description: str | None = None
    active: bool = False
    sort_order: int | None = None


@dataclass(frozen=True)
class ModelCatalogEntry:
    """An admin-configured model that founders can choose for research agents."""

    id: str
    model_id: str
    label: str
    active: bool = False
    is_default: bool = False
    web_capable: bool = False


@dataclass(frozen=True)
class ScoutRun:
    """One Idea Scout run — one founder asking for ideas once."""

    id: str
    owner_sub: str
    build_type: str
    complexity: int
    #: The causation chain this run's agent runs share. Generated before the
    #: agent runs are requested, so it cannot be the run's own id.
    chain_id: str
    status: str
    research_run_ids: list[str] = field(default_factory=list)
    synthesis_run_id: str | None = None
    profile_snapshot: dict[str, object] | None = None
    #: Weight-preference keys the founder chose for this run (#34). Empty
    #: means none expressed, which is a real answer rather than a missing one.
    preferences: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    created_at: str | None = None
    deleted: bool = False
    #: The catalog entry ID the founder chose for research models, or None if
    #: the admin's configured default was used instead.
    research_model: str | None = None


@dataclass(frozen=True)
class Candidate:
    """A stored candidate idea, as read back for the founder."""

    id: str
    run_id: str
    rank: int
    title: str
    pitch: str
    scorecard: dict[str, object] | None = None
    sources: list[dict[str, object]] = field(default_factory=list)
    model: str | None = None


@dataclass(frozen=True)
class AgentRunView:
    """A read of an async agent run (Core's AgentRun) — just what the plugin
    needs to decide whether it is done and to extract its output-tool call."""

    id: str
    status: str
    messages: list[dict[str, object]] = field(default_factory=list)
    model: str | None = None
    #: When a runtime claimed this run. None means nothing ever picked it up.
    started_at: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in RUN_TERMINAL

    @property
    def succeeded(self) -> bool:
        return self.status == RUN_COMPLETED

    @property
    def never_started(self) -> bool:
        """Terminal, unsuccessful, and never claimed by a runtime.

        A run reaches `running` only by being claimed, so `started_at` is the
        structural signal that nothing ever picked this one up — Core's reaper
        fails it after `agent_run_unclaimed_after_seconds` (biffo-template#786).

        Deliberately NOT a substring match on Core's error text. The reaper's
        message is prose that can be reworded, and this project has twice
        shipped a guard that keyed on a spelling and then blocked its own
        correct fix. `started_at is None` is the property.
        """
        return self.is_terminal and not self.succeeded and self.started_at is None
