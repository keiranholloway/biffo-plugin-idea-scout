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
class ScoutRun:
    """One Idea Scout run — one founder asking for ideas once."""

    id: str
    owner_sub: str
    build_type: str
    complexity: int
    status: str
    research_run_ids: list[str] = field(default_factory=list)
    synthesis_run_id: str | None = None
    profile_snapshot: dict[str, object] | None = None
    failure_reason: str | None = None
    created_at: str | None = None
    deleted: bool = False


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

    @property
    def is_terminal(self) -> bool:
        return self.status in RUN_TERMINAL

    @property
    def succeeded(self) -> bool:
        return self.status == RUN_COMPLETED
