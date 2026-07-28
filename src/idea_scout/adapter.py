"""The HTTP ``CoreGateway`` — binds the orchestration's port to Core's seams.

The adapter side of the hexagon: it translates each :class:`CoreGateway` method
into a call to a Core endpoint and parses the response back into a domain object.
It is deliberately **pure** — it takes a ``Transport`` and does no signing, HTTP
or AWS itself — so the whole mapping is testable with a fake transport.

Seam mapping:

- run/candidate rows -> ``/api/v1/internal/owner-data/<table>`` (ADR-0017 §5).
  The owner is stamped by Core from the forwarded token, so ``owner_sub`` is
  **never** sent in a body or param; the adapter relies on Core's owner-scoping
  and ignores the ``owner_sub`` the port passes (fakes use it instead).
- agent runs -> ``/api/v1/internal/agent-runs`` (ADR-0017 §4), created with an
  ``input_payload`` and **no thread**: Idea Scout has no conversation.
- the founder's profile -> ``/api/v1/internal/user-profile/mine``.
- admin-editable agent config -> ``/api/v1/internal/plugins/me/config/<role>``.
- build types -> the plugin's own generic-CRUD route, which is tenant-scoped and
  admin-managed rather than owner-scoped.

JSON-bearing columns are stored as ``Text`` (Core's plugin-table type map has no
JSON type — an unknown type silently degrades to ``String`` and would truncate),
so they are serialised here on the way out and parsed on the way back in. Nothing
above this file should know that.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from .models import RESEARCHING, AgentRunView, BuildType, Candidate, ScoutRun, UserProfile

_ROOT = "/api/v1/internal"
_RUNS = f"{_ROOT}/owner-data/idea_scout_runs"
_CANDIDATES = f"{_ROOT}/owner-data/idea_scout_candidates"
_AGENT_RUNS = f"{_ROOT}/agent-runs"
_USER_PROFILE = f"{_ROOT}/user-profile/mine"
_PLUGIN_CONFIG = f"{_ROOT}/plugins/me/config"
# The manifest declares /build-types as a Core-generated CRUD route, so Core
# serves it twice: publicly at /api/v1/plugins/idea-scout/build-types, and again
# under /api/v1/internal/ (Core's #652 mount). Only the internal one is
# reachable from here — API Gateway routes ALL of /api/v1/plugins/* to the shared
# plugin host (ADR-0021), so the public path sends this plugin's own call back
# into the host, whose founder gate reads Authorization/X-Biffo-Founder-Token and
# not the X-Biffo-User-Token this transport forwards. Hence 401, and every run
# failing at start. Like every other constant here, it must go to Core.
_BUILD_TYPES = f"{_ROOT}/plugins/idea-scout/build-types"


class CoreHttpError(Exception):
    """A Core call failed (non-2xx other than the not-found the adapter handles)."""


class CoreNotFoundError(CoreHttpError):
    """A Core call returned 404 — mapped to ``None`` for the optional reads."""


class Transport(Protocol):
    """The one network boundary. An implementation SigV4-signs the request as the
    plugin's service principal and forwards the founder's Cognito token; it returns
    the parsed JSON body on 2xx, raises :class:`CoreNotFoundError` on 404, and
    :class:`CoreHttpError` on any other non-2xx."""

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any: ...


def _load_json(value: Any, *, default: Any) -> Any:
    """Parse a Text column holding JSON. Tolerates an already-parsed value (a
    JSON-typed transport, or a fake) and a null/empty column."""
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # A column that isn't valid JSON is corrupt data, not a reason to
            # 500 a founder's whole run listing — degrade to the default.
            return default
    return value


def _run_from_row(row: dict[str, Any]) -> ScoutRun:
    return ScoutRun(
        id=row["id"],
        owner_sub=row["owner_sub"],
        build_type=row["build_type"],
        complexity=row["complexity"],
        chain_id=row["chain_id"],
        status=row["status"],
        research_run_ids=_load_json(row.get("research_run_ids"), default=[]),
        synthesis_run_id=row.get("synthesis_run_id"),
        profile_snapshot=_load_json(row.get("profile_snapshot"), default=None),
        preferences=_load_json(row.get("preferences"), default=[]) or [],
        failure_reason=row.get("failure_reason"),
        created_at=row.get("created_at"),
        deleted=row.get("deleted") or False,
    )


def _candidate_from_row(row: dict[str, Any]) -> Candidate:
    return Candidate(
        id=row["id"],
        run_id=row["run_id"],
        rank=row["rank"],
        title=row["title"],
        pitch=row["pitch"],
        scorecard=_load_json(row.get("scorecard"), default=None),
        sources=_load_json(row.get("sources"), default=[]),
        model=row.get("model"),
    )


def _build_type_from_row(row: dict[str, Any]) -> BuildType:
    return BuildType(
        id=row["id"],
        key=row["key"],
        label=row["label"],
        description=row.get("description"),
        active=bool(row.get("active")),
        sort_order=row.get("sort_order"),
    )


class CoreHttpGateway:
    """A :class:`~idea_scout.ports.CoreGateway` backed by Core's HTTP seams."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    # ── The founder ──────────────────────────────────────────────────────────

    async def get_user_profile(self, *, owner_sub: str) -> UserProfile:
        """Core returns 200 with an all-empty shape when the founder has saved
        nothing, so there is no not-found case to handle. A 404 would mean the
        seam is missing entirely (an un-upgraded Core) — surfaced rather than
        silently treated as an empty profile, because a run briefed on nothing
        looks identical to one where the read broke."""
        row = await self._t.request("GET", _USER_PROFILE)
        return UserProfile(
            headline=row.get("headline"),
            years_experience=row.get("years_experience"),
            founder_before=bool(row.get("founder_before")),
            founder_history=row.get("founder_history"),
            commitment_level=row.get("commitment_level"),
            bio=row.get("bio"),
            focus_areas=list(row.get("focus_areas") or []),
            strengths=list(row.get("strengths") or []),
        )

    # ── Admin-configured inputs ──────────────────────────────────────────────

    async def list_build_types(self, *, active_only: bool = True) -> list[BuildType]:
        rows = await self._t.request("GET", _BUILD_TYPES)
        types = [_build_type_from_row(row) for row in rows]
        if active_only:
            types = [t for t in types if t.active]
        # sort_order is optional and admin-entered; fall back to label so the
        # picker is never in insertion order.
        return sorted(
            types, key=lambda t: (t.sort_order if t.sort_order is not None else 0, t.label)
        )

    async def get_own_config(self, *, role: str) -> dict[str, Any] | None:
        """SigV4-only internal read (this data isn't founder-owned). ``None`` when
        never configured — the caller falls back to the built-in default."""
        try:
            row = await self._t.request("GET", f"{_PLUGIN_CONFIG}/{role}")
        except CoreNotFoundError:
            return None
        return {"system_prompt": row["system_prompt"], "model": row["model"]}

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
    ) -> ScoutRun:
        row = await self._t.request(
            "POST",
            _RUNS,
            json={
                "build_type": build_type,
                "complexity": complexity,
                "chain_id": chain_id,
                "status": RESEARCHING,
                "research_run_ids": json.dumps(research_run_ids),
                "profile_snapshot": json.dumps(profile_snapshot),
                "preferences": json.dumps(preferences),
                "deleted": False,
            },
        )
        return _run_from_row(row)

    async def get_run(self, *, owner_sub: str, run_id: str) -> ScoutRun | None:
        try:
            row = await self._t.request("GET", f"{_RUNS}/{run_id}")
        except CoreNotFoundError:
            return None
        return _run_from_row(row)

    async def list_runs(self, *, owner_sub: str) -> list[ScoutRun]:
        # No params: Core's owner-data list route already scopes to the caller
        # via the forwarded token.
        rows = await self._t.request("GET", _RUNS)
        return [_run_from_row(row) for row in rows]

    async def update_run(self, *, run_id: str, **fields: Any) -> None:
        body = dict(fields)
        # The two JSON-bearing columns are the caller's plain Python values;
        # serialise here so no caller has to know the column is Text.
        for column in ("research_run_ids", "profile_snapshot", "preferences"):
            if column in body and not isinstance(body[column], str):
                body[column] = json.dumps(body[column])
        await self._t.request("PATCH", f"{_RUNS}/{run_id}", json=body)

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
        # No thread_id: this run's whole context is input_payload. The output
        # tool rides on the definition snapshot as `output_tools`, which is what
        # makes it a structured-output tool rather than a registry lookup.
        #
        # causation_id is what makes the parallel research runs a *set*. Without
        # it each would be its own chain root and the engine's fan-in would
        # never recognise them as siblings.
        snapshot = {**definition, "output_tools": [output_tool]}
        run = await self._t.request(
            "POST",
            _AGENT_RUNS,
            json={
                "agent_name": agent_name,
                "definition_snapshot": snapshot,
                "input_payload": input_payload,
                "causation_id": causation_id,
            },
        )
        return run["id"]

    async def find_chain_run(self, *, chain_id: str, agent_name: str) -> AgentRunView | None:
        """Look up a run the orchestration engine created in this chain.

        The chain listing returns *summaries* (no transcript), so this fetches
        the full run once it finds one — the caller needs the messages to
        extract the structured output.
        """
        rows = await self._t.request(
            "GET", _AGENT_RUNS, params={"causation_id": chain_id, "agent_name": agent_name}
        )
        if not rows:
            return None
        return await self.get_agent_run(run_id=rows[0]["id"])

    async def get_agent_run(self, *, run_id: str) -> AgentRunView | None:
        try:
            run = await self._t.request("GET", f"{_AGENT_RUNS}/{run_id}")
        except CoreNotFoundError:
            return None
        result = run.get("result") or {}
        model = result.get("model") or (run.get("definition_snapshot") or {}).get("model")
        return AgentRunView(
            id=run["id"],
            status=run["status"],
            messages=run.get("messages") or [],
            model=model,
            started_at=run.get("started_at"),
        )

    # ── Candidates ───────────────────────────────────────────────────────────

    async def save_candidates(
        self, *, run_id: str, candidates: list[dict[str, Any]], model: str | None
    ) -> None:
        """One POST per candidate: generic CRUD has no bulk create. Sequential
        rather than gathered — these are writes through a single founder request,
        and a burst of parallel POSTs buys little against Core's own latency
        while making a partial failure harder to reason about."""
        for rank, candidate in enumerate(candidates, start=1):
            await self._t.request(
                "POST",
                _CANDIDATES,
                json={
                    "run_id": run_id,
                    "rank": rank,
                    "title": candidate["title"],
                    "pitch": candidate["pitch"],
                    "scorecard": json.dumps(candidate.get("scorecard")),
                    "sources": json.dumps(candidate.get("sources") or []),
                    "model": model,
                },
            )

    async def list_candidates(self, *, owner_sub: str, run_id: str) -> list[Candidate]:
        rows = await self._t.request("GET", _CANDIDATES, params={"run_id": run_id})
        return sorted(
            (_candidate_from_row(row) for row in rows),
            key=lambda c: c.rank,
        )
