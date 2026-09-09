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

import logging
import os
from typing import Any

from biffo_plugin_sdk import ForwardedUser, require_group
from fastapi import Depends, FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .adapter import CoreHttpError, CoreHttpGateway
from .definitions import (
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    MAX_CADENCE_DAYS,
    MAX_COMPLEXITY,
    MIN_CADENCE_DAYS,
    MIN_COMPLEXITY,
    PREFERENCES,
    complexity_label,
    seed_config_payloads,
)
from .models import IN_FLIGHT_STATUSES
from .service import (
    AgentConfigMissingError,
    IdeaScoutError,
    IdeaScoutService,
    InvalidCadenceError,
    InvalidComplexityError,
    MalformedCandidatesError,
    RunNotFoundError,
    UnknownBuildTypeError,
    UnknownBusinessModelError,
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
_RESEARCH_MODEL = os.environ.get("IDEA_SCOUT_RESEARCH_MODEL", DEFAULT_RESEARCH_MODEL)
_SYNTHESIS_MODEL = os.environ.get("IDEA_SCOUT_SYNTHESIS_MODEL", DEFAULT_SYNTHESIS_MODEL)

#: The founder gate — verifies the shared-Cognito JWT and requires the group.
#: The verified user carries its raw token, forwarded to Core by the transport.
require_founder = require_group("founder")

_LOGGER = logging.getLogger(__name__)


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


@app.on_event("startup")
async def _seed_agent_config() -> None:
    """Seed the agent config on startup, tolerating a failed seed.

    Seeding guarantees rows exist so _resolve_agent can fail loudly on a missing
    row rather than silently using the fallback. If the seed fails for any reason,
    the plugin continues anyway — the absence will fail loudly when a founder
    tries to run.

    **The log line must not name a cause it has not established.** It used to say
    "Core may be unavailable", and on 2026-07-31 that was read as the diagnosis:
    Core was up and had answered, with a 500 from its own unique constraint
    (biffo-template#924). The speculation cost the first theory. ``CoreHttpError``
    already carries the method, path, status and response body — report those and
    let them say what happened.
    """
    try:
        transport = CoreTransport(founder_token="")
        gateway = CoreHttpGateway(transport)
        payload = seed_config_payloads(
            research_model=_RESEARCH_MODEL, synthesis_model=_SYNTHESIS_MODEL
        )
        result = await gateway.seed_own_config(config=payload)
        created = sum(1 for r in result if r.get("created"))
        already_present = len(result) - created
        _LOGGER.info(f"Seeded {created} new agent config row(s); {already_present} already present")
    except CoreHttpError as exc:
        _LOGGER.exception(
            "Failed to seed agent config at startup. Core's response: %s. "
            "Agent runs will fail loudly when started until the rows exist.",
            exc,
        )


# Orchestration errors -> HTTP. Registered once for the base class; the map keys
# on the concrete type. Anything unmapped is a 400 (a bad request the founder
# can fix). Note there is no mapping for an agent failing: that is a *run state*
# carrying a reason the founder can read, not an HTTP error (see service.py).
_ERROR_STATUS: dict[type[IdeaScoutError], int] = {
    RunNotFoundError: 404,
    UnknownBuildTypeError: 422,
    UnknownBusinessModelError: 422,
    InvalidComplexityError: 422,
    InvalidCadenceError: 422,
    UnknownPreferenceError: 422,
    UnknownModelError: 422,
    MalformedCandidatesError: 502,
    AgentConfigMissingError: 502,
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
    # How the founder wants the idea to make money. Optional and defaulted None:
    # unlike build_type this does NOT gate a run, because a founder may genuinely
    # have no preference and defaulting to one would scope every run from an input
    # they never made. Validated against the active list in the service, next to
    # the build type, so both rejections read the same way.
    business_model: str | None = Field(default=None, max_length=64)


class CadenceRequest(BaseModel):
    """What the cadence control submits (#50).

    Both fields are required and always sent together. ``enabled`` false is an
    explicit OFF — a real answer the founder gave, not an omission — and
    ``cadence_days`` is still carried with it so switching back on restores the
    interval they chose rather than silently resetting to the default.

    The range is enforced here *and* in the service. Here it is a 422 the client
    can act on; there it is the rule itself, which a second caller must not be
    able to route around. Same arrangement as ``complexity`` above.
    """

    enabled: bool
    cadence_days: int = Field(ge=MIN_CADENCE_DAYS, le=MAX_CADENCE_DAYS)


def _cadence_json(state: Any) -> dict[str, Any]:
    """The cadence as the surface needs it — the preference, the bounds it must
    stay inside, and the two derived facts.

    ``next_due_at`` and ``is_due`` are computed on every read from the stored
    interval and the founder's latest run (see ``service._derive_cadence_state``).
    Neither is stored, so neither can disagree with the preference beside it.
    """
    return {
        "enabled": state.enabled,
        "cadence_days": state.cadence_days,
        "min_cadence_days": MIN_CADENCE_DAYS,
        "max_cadence_days": MAX_CADENCE_DAYS,
        "next_due_at": state.next_due_at,
        "is_due": state.is_due,
    }


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
        # Echoed for the same reason preferences are: a past run stays explicable
        # after the founder changes their mind. None means "no preference".
        "business_model": run.business_model,
    }


def _build_type_json(t: Any) -> dict[str, Any]:
    return {"key": t.key, "label": t.label, "description": t.description}


def _business_model_json(m: Any) -> dict[str, Any]:
    return {"key": m.key, "label": m.label, "description": m.description}


def _model_option_json(m: Any) -> dict[str, Any]:
    return {"id": m.id, "model_id": m.model_id, "label": m.label, "is_default": m.is_default}


def _preferences_json() -> list[dict[str, Any]]:
    return [dict(p) for p in PREFERENCES]


def _complexity_levels_json() -> list[dict[str, Any]]:
    return [
        {"value": level, "label": complexity_label(level)}
        for level in range(MIN_COMPLEXITY, MAX_COMPLEXITY + 1)
    ]


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
    return [_build_type_json(t) for t in await svc.list_build_types()]


@app.get("/business-models")
async def list_business_models(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> list[dict]:
    """The active business-model categories, for the run form's picker.

    Carries no valuation, multiple or price figure — see the table's manifest
    description for why.
    """
    return [_business_model_json(m) for m in await svc.list_business_models()]


@app.get("/models")
async def list_models(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> list[dict]:
    """The active, web-capable models founders can choose for research agents."""
    return [_model_option_json(m) for m in await svc.list_model_catalog()]


@app.get("/models/last-used")
async def get_last_used_model(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> dict:
    """The model slug from this founder's most recent run, if any.

    Returns the research_model of the newest run, or None if no run has set one.
    This is owner-scoped: only this founder's runs are considered.
    """
    runs = await svc.list_runs(owner_sub=founder.sub)
    for run in runs:
        if run.research_model:
            return {"research_model": run.research_model}
    return {"research_model": None}


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
    return _preferences_json()


@app.get("/complexity-levels")
async def list_complexity_levels(
    founder: ForwardedUser = Depends(require_founder),
) -> list[dict]:
    """The slider's positions and what each one means.

    Served rather than hardcoded in the frontend so the wording the founder
    reads is the same wording the agents are briefed with — two copies would
    drift, and the UI's copy is the one that would be wrong.
    """
    return _complexity_levels_json()


@app.get("/form-options")
async def form_options(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> dict[str, Any]:
    """Everything the run form needs to render, in one request.

    Exists for a concurrency reason, not an aesthetic one. Every
    ``/api/v1/plugins/idea-scout/*`` call is served by the *shared plugin host*
    (ADR-0021), whose handler then calls Core's internal API — so each request
    the page makes costs two Lambda invocations, not one. The founder app used
    to fetch these five lists separately on mount, which asked for ~10
    concurrent invocations against an account ceiling of 10 and throttled
    itself; API Gateway renders a Lambda throttle as
    ``503 {"message":"Service Unavailable"}`` (#79).

    The three Core-backed lists are awaited **in sequence, not gathered**. Under
    a tight concurrency ceiling, serialising is the point: three sequential
    reads hold one Core slot at a time for ~100ms each, where gathering holds
    three at once. The page is a few hundred milliseconds slower and
    dramatically less likely to throttle.

    Each list is shaped by the same helper its individual endpoint uses, so the
    two can never drift — asserted in test_idea_scout_app.py.

    **The cadence rides along for the same concurrency reason**, even though it
    is not strictly a run-form input (#50). The page needs it on mount — it is
    what decides whether a returning founder gets a scout started for them —
    and asking for it separately would have made this a four-request mount, or
    eight Lambda invocations against a ceiling of ten. ``GET /cadence`` still
    exists and is still what the surface re-reads after a run starts; this is
    the bootstrap, not a replacement for it. Same helper again, so the two
    cannot drift.
    """
    build_types = await svc.list_build_types()
    business_models = await svc.list_business_models()
    models = await svc.list_model_catalog()
    cadence = await svc.cadence_state(owner_sub=founder.sub)
    return {
        "build_types": [_build_type_json(t) for t in build_types],
        "business_models": [_business_model_json(m) for m in business_models],
        "models": [_model_option_json(m) for m in models],
        "preferences": _preferences_json(),
        "complexity_levels": _complexity_levels_json(),
        "cadence": _cadence_json(cadence),
    }


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
        business_model=body.business_model,
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


@app.get("/cadence")
async def read_cadence(
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> dict[str, Any]:
    """This founder's auto-scout cadence, and whether a scout is due right now.

    The surface reads ``is_due`` and acts on it; it does **not** recompute
    staleness from ``created_at`` against a constant of its own. It used to, and
    that constant was the same value in two languages — the interval being
    founder-configurable is precisely what makes a second copy untenable.

    The bounds ride along for the same reason ``/complexity-levels`` serves its
    labels: the number input's ``min``/``max`` must be the range the API will
    actually accept, and two copies would drift with the frontend's the one
    that is wrong.
    """
    return _cadence_json(await svc.cadence_state(owner_sub=founder.sub))


@app.put("/cadence")
async def write_cadence(
    body: CadenceRequest,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> dict[str, Any]:
    """Set the interval, or turn the auto-scout off.

    Returns the same shape the GET does, recomputed — so the caller sees the
    new ``next_due_at`` and ``is_due`` that follow from what it just saved,
    without a second round trip and without deriving either for itself.

    ``PUT`` rather than ``POST``: there is exactly one cadence per founder and
    this replaces it, so repeating the call is a no-op rather than a second row.
    Whether it inserts or patches underneath is the service's business.
    """
    await svc.set_cadence(
        owner_sub=founder.sub,
        enabled=body.enabled,
        cadence_days=body.cadence_days,
    )
    return _cadence_json(await svc.cadence_state(owner_sub=founder.sub))


@app.post("/runs/{run_id}/delete", status_code=204)
async def delete_run(
    run_id: str,
    founder: ForwardedUser = Depends(require_founder),
    svc: IdeaScoutService = Depends(get_service),
) -> None:
    """Soft-delete a run — allowed from any status, including in flight."""
    await svc.delete_run(owner_sub=founder.sub, run_id=run_id)
