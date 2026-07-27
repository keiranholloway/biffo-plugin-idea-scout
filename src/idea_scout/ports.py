"""The boundary the orchestration depends on (a hexagonal port).

The real adapter binds this to Core's API seams (ADR-0002 — the plugin never
touches a database); the tests bind it to an in-memory fake. Keeping the logic
behind this interface is what lets the fan-out/fan-in be tested exhaustively
without a network, a runtime, or an LLM.

Everything here is reached under the founder's own authority: the transport
signs as this plugin's service principal *and* forwards the founder's token, so
Core stamps and enforces the owner. ``owner_sub`` is still passed on the reads
for parity with non-HTTP adapters and fakes — the HTTP adapter ignores it and
relies on Core's scoping, which is the authority (ADR-0017 §5).
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import AgentRunView, BuildType, Candidate, ScoutRun, UserProfile


class CoreGateway(Protocol):
    """Everything the orchestration needs from Core."""

    # ── The founder ──────────────────────────────────────────────────────────

    async def get_user_profile(self, *, owner_sub: str) -> UserProfile:
        """The founder's own profile, via Core's internal service-authenticated
        read. Never raises for "no profile" — Core returns the empty shape, and
        a founder who has saved nothing still gets a (less targeted) run."""
        ...

    # ── Admin-configured inputs ──────────────────────────────────────────────

    async def list_build_types(self, *, active_only: bool = True) -> list[BuildType]:
        """The build-type categories offered in the run form, ascending by
        ``sort_order``. Admin-managed through generic CRUD."""
        ...

    async def get_own_config(self, *, role: str) -> dict[str, Any] | None:
        """The live, admin-editable config (``system_prompt`` + ``model``) for one
        of this plugin's own agent roles, or ``None`` if never configured — in
        which case the caller falls back to the built-in default."""
        ...

    # ── Runs ─────────────────────────────────────────────────────────────────

    async def create_run(
        self,
        *,
        owner_sub: str,
        build_type: str,
        complexity: int,
        profile_snapshot: dict[str, Any],
        research_run_ids: list[str],
        chain_id: str,
    ) -> ScoutRun: ...

    async def get_run(self, *, owner_sub: str, run_id: str) -> ScoutRun | None: ...

    async def list_runs(self, *, owner_sub: str) -> list[ScoutRun]:
        """Every run owned by this founder, in no particular order — the caller
        sorts, and filters out soft-deleted ones."""
        ...

    async def update_run(self, *, run_id: str, **fields: Any) -> None:
        """Patch a run row. Kept generic rather than one setter per field: the
        service advances several fields together (status plus synthesis_run_id,
        or status plus failure_reason) and doing that in one call keeps a run
        from being observed half-advanced by a concurrent poll."""
        ...

    # ── Agent runs (the runtime) ─────────────────────────────────────────────

    async def request_agent_run(
        self,
        *,
        agent_name: str,
        definition: dict[str, Any],
        output_tool: dict[str, Any],
        input_payload: dict[str, Any],
        causation_id: str,
    ) -> str:
        """Request one async agent run; returns its id.

        No thread: Idea Scout has no conversation, so the run's whole context is
        ``input_payload``. ``output_tool`` is registered as the run's structured
        output tool — never as a registry tool.

        ``causation_id`` is **required**, not optional. It is what makes the
        parallel research runs siblings of one chain, which is the only way the
        orchestration engine's fan-in can recognise them as a set. A run sent
        without one is a chain root, and a fan-in waiting on it would wait
        forever.
        """
        ...

    async def find_chain_run(self, *, chain_id: str, agent_name: str) -> AgentRunView | None:
        """The run of ``agent_name`` in this causation chain, if one exists yet.

        How this plugin discovers a run the **orchestration engine** created on
        its behalf: the engine fires the synthesis agent when the research set
        completes, and nothing tells the plugin its id. Returns ``None`` while
        the engine has not fired it.
        """
        ...

    async def get_agent_run(self, *, run_id: str) -> AgentRunView | None:
        """Read an agent run's state and transcript. ``None`` if Core has no such
        run — treated as a failure by the caller, not as "still running", so a
        vanished run cannot hang a scout forever."""
        ...

    # ── Candidates ───────────────────────────────────────────────────────────

    async def save_candidates(
        self, *, run_id: str, candidates: list[dict[str, Any]], model: str | None
    ) -> None:
        """Persist the ranked shortlist. Sends no owner — Core stamps it from the
        forwarded token, so candidates are owner-scoped like their run."""
        ...

    async def list_candidates(self, *, owner_sub: str, run_id: str) -> list[Candidate]:
        """This run's stored candidates, ascending by rank."""
        ...
