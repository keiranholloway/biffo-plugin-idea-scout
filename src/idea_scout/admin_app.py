"""Idea Scout's admin-facing ASGI app (ADR-0021 ``admin_ingress``).

**This app serves the built admin UI and built-in configuration data.**

``idea_scout_build_types`` already declares its five CRUD routes in
``biffo.plugin.json``'s ``api_routes``, so **Core** generates them and the plugin
host forwards them (biffo-template#684), authorised by the table's own
admin-only permissions. The UI calls
``/api/v1/plugins/idea-scout/build-types`` directly — one hop.

``/builtin-agents`` is served from here because it returns static configuration
(DEFAULT_INSTRUCTIONS, built-in models) that the UI merges with stored rows to
show a complete view — which prompts are code-defined and which have been
promoted to the database. This pattern follows ideation's
``builtin_chat_agents()`` endpoint and is necessary for the "Store a copy to edit"
button to write the real prompt rather than a placeholder.

**Chat-agent CRUD is proxied through here again (#69), and the reasoning that
removed it was half right.** The previous version of this docstring said:

    The previous version of this file proxied CRUD routes through here with
    httpx [...] the host calls itself and then forwards to Core — three hops
    [...] We avoid that by calling Core's declared routes directly.

The cost is real, but it is the cost of the host calling *itself* through the
public path (biffo-template#652). Calling Core directly at ``BIFFO_CORE_API_URL``
is one hop, which is what ``_core_request`` below does and what ideation has
always done.

What "calling Core's declared routes directly" could not survive is the browser:
``/api/v1/admin/*`` **is not routed to Core at all** from ``dev.biffo.io``. The
CDN carries exactly one API behaviour, ``api/v1/plugins/*``; everything else
falls through to the portal origin, which answered those calls with its own HTML
shell and a 403. Build types work because they are declared ``api_routes`` under
``/api/v1/plugins/idea-scout/``; chat agents are Core admin routes and are not.
The portal's own admin pages dodge this by calling an absolute
``NEXT_PUBLIC_API_URL``, which a plugin SPA served from the CDN cannot do without
introducing cross-origin.

So the routes below are plugin-scoped — ``/api/v1/plugins/idea-scout/admin/…`` —
and forward to Core server-side **as the calling admin**, which is the shape
ideation has and the only one of the three that needs no infrastructure change.

Reinstated after biffo-plugin-idea-scout#22, which removed the previous
declaration because it promised a UI that did not exist. Both defects that issue
identified are fixed here: there is now a real ``web-admin/`` tree, and the
static path is resolved from ``BIFFO_PLUGINS_ROOT`` rather than from
``__file__``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from biffo_plugin_sdk import ForwardedUser, require_group
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from idea_scout.adapter import CoreHttpError, CoreHttpGateway
from idea_scout.definitions import (
    COMMUNITY_AGENT_NAME,
    COMPETITIVE_AGENT_NAME,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NARRATIVE_AGENT_NAME,
    SYNTHESIS_AGENT_NAME,
    seed_config_payloads,
)
from idea_scout.transport import CoreTransport

_LOGGER = logging.getLogger(__name__)

require_admin = require_group("admin")

_CORE_API_URL = os.environ.get("BIFFO_CORE_API_URL", "")
_PLUGIN_NAME = "idea-scout"
_CHAT_AGENTS_BASE = f"/api/v1/admin/plugins/{_PLUGIN_NAME}/chat-agents"

#: How long to wait on Core. Explicit, and matching ideation's equivalent: a bare
#: ``httpx.AsyncClient()`` silently carries httpx's own 5s default that nobody
#: chose, and Core cold-starts in ~4.3s of init before it runs a line of handler,
#: so the unchosen default expires on exactly the requests that most need it
#: (biffo-template#652/#724).
_CORE_TIMEOUT_SECONDS = 30.0

app = FastAPI(title="Idea Scout Admin", docs_url=None, redoc_url=None)


async def _core_request(
    method: str, path: str, *, admin: ForwardedUser, json: dict[str, Any] | None = None
) -> Any:
    """Forward one call to Core, authenticated as the calling admin.

    **As the admin, not as this plugin's service principal.** Core's
    ``require_admin`` then authorises the real human on every one of these, so
    proxying adds a hop and no privilege: an operator who is not in the ``admin``
    group gets Core's own 403 back, unchanged.

    This is one hop (host → Core), not the three-hop self-call through the public
    path that cost biffo-template#652 — the URL is Core's own, taken from
    ``BIFFO_CORE_API_URL``.
    """
    url = f"{_CORE_API_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=_CORE_TIMEOUT_SECONDS) as client:
        resp = await client.request(
            method, url, json=json, headers={"Authorization": f"Bearer {admin.token}"}
        )
    if resp.status_code >= 400:
        # Carry Core's status AND body through. The panel renders the detail, and
        # a bare status is what made #69 unreadable: the UI could only say
        # "no agents stored" because nothing told it why the request failed.
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json() if resp.content else None


@app.on_event("startup")
async def _seed_agent_config() -> None:
    """Seed the agent config on startup, tolerating Core transient failures.

    Seeding guarantees rows exist so _resolve_agent can fail loudly on a missing
    row rather than silently using the fallback. If Core is briefly unavailable
    at cold start, the app continues anyway — the absence will fail loudly when
    a founder tries to run.
    """
    try:
        research_model = os.environ.get("IDEA_SCOUT_RESEARCH_MODEL", DEFAULT_RESEARCH_MODEL)
        synthesis_model = os.environ.get("IDEA_SCOUT_SYNTHESIS_MODEL", DEFAULT_SYNTHESIS_MODEL)
        transport = CoreTransport(founder_token="")
        gateway = CoreHttpGateway(transport)
        payload = seed_config_payloads(
            research_model=research_model, synthesis_model=synthesis_model
        )
        result = await gateway.seed_own_config(config=payload)
        created = sum(1 for r in result if r.get("created"))
        already_present = len(result) - created
        _LOGGER.info(f"Seeded {created} new agent config row(s); {already_present} already present")
    except CoreHttpError as exc:
        _LOGGER.exception(
            "Failed to seed agent config at startup (Core may be unavailable). "
            "Agent runs will fail loudly when started: %s",
            exc,
        )


def _resolve_static_dir(plugins_root: str | None) -> Path:
    """Where the built ``web-admin/dist`` actually lands, in either context.

    The deployed plugin-host Lambda flattens this package's ``src/`` into its own
    task root (biffo-platform's ``deploy-app.yml``: ``cp -r "$plugin_dir"/src/.
    "$pkg/"``), so this file ends up at ``<task-root>/idea_scout/admin_app.py``
    — one directory shallower than in a source checkout
    (``<repo>/src/idea_scout/admin_app.py``). **A fixed relative parent count
    cannot resolve correctly in both shapes**, which is the second of the two
    defects in #22: the old code used
    ``Path(__file__).parent.parent.parent / "web-admin" / "dist"`` and would
    have 404'd even once the assets existed.

    ``BIFFO_PLUGINS_ROOT`` is the deployed anchor instead — already set on the
    Lambda for ``discover_plugins()``'s manifest scan, and the same deploy step
    copies this plugin's built output to ``services/idea-scout/web-admin/dist``
    beside the manifest.

    Falls back to the source-repo-relative path when the variable is unset —
    local dev, and this app's own tests.

    Ported from ideation's identical helper (biffo-template#627/#632). That fix
    existed for months before this copy received it; the guard in
    ``tests/test_idea_scout_manifest.py`` now fails if anyone reintroduces the
    ``__file__``-relative form.
    """
    if plugins_root:
        return Path(plugins_root) / "idea-scout" / "web-admin" / "dist"
    return Path(__file__).resolve().parent.parent.parent / "web-admin" / "dist"


@app.get("/chat-agents")
async def list_chat_agents(admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", _CHAT_AGENTS_BASE, admin=admin)


@app.post("/chat-agents", status_code=201)
async def create_chat_agent(
    body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("POST", _CHAT_AGENTS_BASE, admin=admin, json=body)


@app.get("/chat-agents/{agent_key}")
async def get_chat_agent(agent_key: str, admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin)


@app.put("/chat-agents/{agent_key}")
async def update_chat_agent(
    agent_key: str, body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("PUT", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin, json=body)


@app.delete("/chat-agents/{agent_key}", status_code=204)
async def delete_chat_agent(agent_key: str, admin: ForwardedUser = Depends(require_admin)) -> None:
    await _core_request("DELETE", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin)


# RELATIVE path, deliberately. This app is mounted under
# `/api/v1/plugins/idea-scout/admin`, so the absolute path this route used to
# declare — `/api/v1/admin/plugins/idea-scout/builtin-agents` — actually served
# it at `/api/v1/plugins/idea-scout/admin/api/v1/admin/plugins/idea-scout/
# builtin-agents`, a URL nothing calls and nothing could. The route existed, the
# tests passed, and the endpoint was unreachable (#69).
@app.get("/builtin-agents")
def builtin_agents() -> dict:
    """The four code-defined agent roles with their real prompts.

    The UI merges these with stored rows to show the complete picture: which
    prompts are still defined in code and which have been promoted to the
    database. The "Store a copy to edit" button writes the real prompt from here,
    not a placeholder.

    Ported from ideation's equivalent endpoint (builtin_chat_agents).
    """
    return {
        "agents": [
            {
                "agent_key": COMMUNITY_AGENT_NAME,
                "agent_name": COMMUNITY_AGENT_NAME,
                "role": COMMUNITY_AGENT_NAME,
                "system_prompt": DEFAULT_INSTRUCTIONS[COMMUNITY_AGENT_NAME],
                "model": DEFAULT_RESEARCH_MODEL,
                "required_group": "founder",
                "active": True,
                "max_history_messages": 10,
                "max_output_tokens": 2000,
                "timeout_seconds": 30,
            },
            {
                "agent_key": NARRATIVE_AGENT_NAME,
                "agent_name": NARRATIVE_AGENT_NAME,
                "role": NARRATIVE_AGENT_NAME,
                "system_prompt": DEFAULT_INSTRUCTIONS[NARRATIVE_AGENT_NAME],
                "model": DEFAULT_RESEARCH_MODEL,
                "required_group": "founder",
                "active": True,
                "max_history_messages": 10,
                "max_output_tokens": 2000,
                "timeout_seconds": 30,
            },
            {
                "agent_key": COMPETITIVE_AGENT_NAME,
                "agent_name": COMPETITIVE_AGENT_NAME,
                "role": COMPETITIVE_AGENT_NAME,
                "system_prompt": DEFAULT_INSTRUCTIONS[COMPETITIVE_AGENT_NAME],
                "model": DEFAULT_RESEARCH_MODEL,
                "required_group": "founder",
                "active": True,
                "max_history_messages": 10,
                "max_output_tokens": 2000,
                "timeout_seconds": 30,
            },
            {
                "agent_key": SYNTHESIS_AGENT_NAME,
                "agent_name": SYNTHESIS_AGENT_NAME,
                "role": SYNTHESIS_AGENT_NAME,
                "system_prompt": DEFAULT_INSTRUCTIONS[SYNTHESIS_AGENT_NAME],
                "model": DEFAULT_SYNTHESIS_MODEL,
                "required_group": "founder",
                "active": True,
                "max_history_messages": 10,
                "max_output_tokens": 2000,
                "timeout_seconds": 30,
            },
        ]
    }


# ── static UI, mounted LAST ──────────────────────────────────────────────────
#
# Order is load-bearing and was the third half of #69. Starlette matches routes
# in REGISTRATION order and `Mount("/")` matches every path, so anything declared
# after it is unreachable — there is no fall-through to a later route. This block
# used to sit above the API routes, which is why even a correctly-pathed
# `/builtin-agents` would still have returned the SPA's index.html.
#
# Ideation mounts last for the same reason. `tests/test_admin_app.py` asserts the
# ordering rather than trusting a comment: a mount that creeps back up the file
# takes the whole API down silently, and every unit test would still pass because
# they call the app object directly.
#
# Mounted conditionally: `web-admin/dist` is a build artefact, absent in a source
# checkout and in this app's own tests. An unbuilt UI must not stop the app
# importing — but note that a *deployed* plugin declaring `admin_ingress` with no
# `web-admin/` now fails the deploy outright (biffo-template#793), so this
# fallback can no longer hide a missing UI in production the way it did in #22.
_STATIC_DIR = _resolve_static_dir(os.environ.get("BIFFO_PLUGINS_ROOT"))
if _STATIC_DIR.is_dir():  # pragma: no cover — depends on a build having run
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="admin-ui")
