"""Idea Scout's founder-facing ASGI app (ADR-0021).

A FastAPI app mounted by the shared plugin host at
``/api/v1/plugins/idea-scout/*``. The host authenticates the founder (its group
gate verifies the shared-Cognito JWT and requires the ``founder`` group) before
dispatching here; this app *also* runs ``require_group("founder")`` per route —
defence-in-depth, and the way it obtains the founder's token to forward to Core
so Core owns identity and owner-scoping (ADR-0017 §3/§5). It holds **no data**
(ADR-0002).

``app`` is what the manifest's ``user_ingress`` names as ``idea_scout.app:app``;
the host provides the Lambda entrypoint and strips the mount prefix, so the
routes below stay clean and the app is agnostic to where it is mounted.

Reading a run is a **write** in disguise: polling is what advances the state
machine (see service.py). That is why ``GET /runs/{id}`` is not cacheable and
why the sidebar's ``GET /runs`` deliberately does not advance anything.
"""

from __future__ import annotations

import os
from typing import Any

from biffo_plugin_sdk import ForwardedUser, require_group
from fastapi import Depends, FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .adapter import CoreHttpGateway
from .definitions import MAX_COMPLEXITY, MIN_COMPLEXITY, PREFERENCES, complexity_label
from .models import IN_FLIGHT_STATUSES
from .service import (
    IdeaScoutError,
    IdeaScoutService,
    InvalidComplexityError,
    MalformedCandidatesError,
    RunNotFoundError,
    UnknownBuildTypeError,
    UnknownModelError,
    UnknownPreferenceError,
)
from .transport import CoreTransport

# Research runs on an OpenRouter ``:online`` model: the suffix attaches live web
# results to the turn, so the search capability travels with the model id and
# cannot be half-configured. The previous arrangement — a plain model plus the
# ``web_search`` registry tool — failed open on a deployment with no Brave
# credential: the tool was silently dropped and every run produced no findings.
# Synthesis does not search; it reasons over what research hands it.
_RESEARCH_MODEL = os.environ.get("IDEA_SCOUT_RESEARCH_MODEL", "anthropic/claude-sonnet-4:online")
_SYNTHESIS_MODEL = os.environ.get("IDEA_SCOUT_SYNTHESIS_MODEL", "anthropic/claude-opus-4-8")

#: The founder gate — verifies the shared-Cognito JWT and requires the group.
#: The verified user carries its raw token, forwarded to Core by the transport.
require_founder = require_group("founder")


def get_service(founder: ForwardedUser = Depends(require_founder)) -> IdeaScoutService:
    """One :class:`IdeaScoutService` per request, bound to Core over a transport
    that signs as this Lambda AND forwards *this* founder's token."""
    transport = CoreTransport(founder_token=founder.token)
    return IdeaScoutService(
        CoreHttpGateway(transport),
        research_model=_RESEARCH_MODEL,
        synthesis_model=_SYNTHESIS_MODEL,
    )


app = FastAPI(title="Idea Scout", docs_url=None, redoc_url=None)

# Orchestration errors -> HTTP. Registered once for the base class; the map keys
# on the concrete type. Anything unmapped is a 400 (a bad request the founder
# can fix). Note there is no mapping for an agent failing: that is a *run state*
# carrying a reason the founder can read, not an HTTP error (see service.py).
_ERROR_STATUS: dict[type[IdeaScoutError], int] = {
    RunNotFoundError: 404,
    UnknownBuildTypeError: 422,
    InvalidComplexityError: 422,
    UnknownPreferenceError: 422,
    UnknownModelError: 422,
    MalformedCandidatesError: 502,
}


@app.exception_handler(IdeaScoutError)
async def _on_idea_scout_error(_: Request, exc: IdeaScoutError) -> JSONResponse:
    status = _ERROR_STATUS.get(type(exc), 400)
    return JSONResponse(status_code=status, content={"detail": str(exc) or type(exc).__name__})


class StartRunRequest(BaseModel):
    """What the run form submits.

    ``build_type`` is a key, never a label: labels are admin-editable and a run
    stores what it was started for. It is validated server-side against the
    *active* list — a client could send an inactive or invented one.
    """

    build_type: str = Field(min_length=1, max_length=64)
    complexity: int = Field(ge=MIN_COMPLEXITY, le=MAX_COMPLEXITY)
    # Weight preferences (#34). Optional and defaulted empty: expressing none is
    # a real answer, and defaulting to any subset would shape results from an
    # input the founder never made. Keys are validated against the known set in
    # the service, not here — the same place the build type is checked, so both
    # rejections read the same way.
    preferences: list[str] = Field(default_factory=list, max_length=len(PREFERENCES))
    # The catalog entry ID the founder chose for research agents. Optional;
    # when not specified, the admin's configured model or built-in default is used.
    research_model: str | None = None


def _run_state(run: Any) -> dict[str, Any]:
    """The run as the UI needs it: enough to decide whether to keep polling,
    render candidates, or show a failure."""
    return {
        "run_id": run.id,
        "status": run.status,
        "build_type": run.build_type,
        "complexity": run.complexity,
        "complexity_label": complexity_label(run.complexity),
        # Echoed back so the UI can show what a past run was actually asked for
        # — a run stays explicable after the founder changes their mind (#34).
        "preferences": list(run.preferences),
        "created_at": run.created_at,
        "in_flight": run.status in IN_FLIGHT_STATUSES,
        "failure_reason": run.failure_reason,
        "research_model": run.research_model,
    }


def _candidate_json(candidate: Any) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "rank": candidate.rank,
        "title": candidate.title,
        "pitch": candidate.pitch,
        "scorecard": candidate.scorecard,
        "sources": candidate.sources,
    }


@app.get("/build-types")
async def list_build_types(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> list[dict]:
    """The active build-type categories, for the run form's picker."""
    types = await svc.list_build_types()
    return [{"key": t.key, "label": t.label, "description": t.description} for t in types]


@app.get("/models")
async def list_models(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> list[dict]:
    """The active, web-capable models founders can choose for research agents."""
    models = await svc.list_model_catalog()
    return [
        {
            "id": m.id,
            "model_id": m.model_id,
            "label": m.label,
            "is_default": m.is_default,
        }
        for m in models
    ]


@app.get("/preferences")
async def list_preferences(
    founder: ForwardedUser = Depends(require_founder),
) -> list[dict]:
    """The weight preferences a founder can express, and which way each leans.

    Served rather than hardcoded in the frontend for the same reason as the
    complexity levels: the wording the founder reads must be the wording the
    agents are briefed with. Two copies drift, and the UI's is the one that
    would be wrong.
    """
    return [dict(p) for p in PREFERENCES]


@app.get("/complexity-levels")
async def list_complexity_levels(
    founder: ForwardedUser = Depends(require_founder),
) -> list[dict]:
    """The slider's positions and what each one means.

    Served rather than hardcoded in the frontend so the wording the founder
    reads is the same wording the agents are briefed with — two copies would
    drift, and the UI's copy is the one that would be wrong.
    """
    return [
        {"value": level, "label": complexity_label(level)}
        for level in range(MIN_COMPLEXITY, MAX_COMPLEXITY + 1)
    ]


@app.post("/runs", status_code=201)
async def start_run(
    body: StartRunRequest,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> dict:
    """Start a scout: reads the founder's profile, briefs the research agents,
    and returns the run to poll."""
    run = await svc.start_run(
        owner_sub=founder.sub,
        build_type=body.build_type,
        complexity=body.complexity,
        preferences=body.preferences,
        research_model=body.research_model,
    )
    return _run_state(run)


@app.get("/runs")
async def list_runs(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> list[dict]:
    """This founder's runs, most-recent-first — for the sidebar.

    Deliberately does not advance any run's state machine; see
    ``IdeaScoutService.list_runs`` for why.
    """
    runs = await svc.list_runs(owner_sub=founder.sub)
    return [_run_state(run) for run in runs]


@app.get("/runs/{run_id}")
async def read_run(
    run_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> dict:
    """A run's current state. **This is the polling endpoint**, and polling is
    what moves the run forward — research to synthesis, synthesis to complete."""
    return _run_state(await svc.get_run(owner_sub=founder.sub, run_id=run_id))


@app.get("/runs/{run_id}/candidates")
async def read_candidates(
    run_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> dict:
    """The ranked shortlist, empty while the run is still in flight.

    Returns the run's state alongside so a client polling only this endpoint
    still knows whether to keep waiting or to stop and show a failure.
    """
    candidates = await svc.get_candidates(owner_sub=founder.sub, run_id=run_id)
    run = await svc.get_run(owner_sub=founder.sub, run_id=run_id)
    return {
        **_run_state(run),
        "candidates": [_candidate_json(c) for c in candidates],
    }


@app.post("/runs/{run_id}/delete", status_code=204)
async def delete_run(
    run_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> None:
    """Soft-delete a run — allowed from any status, including in flight."""
    await svc.delete_run(owner_sub=founder.sub, run_id=run_id)
