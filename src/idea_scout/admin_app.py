"""Idea Scout's admin-facing ASGI app (ADR-0021 ``admin_ingress``).

A FastAPI app mounted by the shared plugin host at
``/api/v1/plugins/idea-scout/admin/*`` — admin-gated both by the host's own group
gate and, defence-in-depth, by this app's ``require_group("admin")``. It proxies
Core's admin routes for build types and agent config as same-origin routes, and
serves the built admin UI.

Unlike ``app.py``'s founder-facing ``CoreTransport`` (SigV4-signed as this
plugin's service principal, forwarding a founder token for dual-auth), these Core
routes need only the calling admin's own Cognito token forwarded as-is:
``require_admin`` on the Core side checks it is a valid admin token, with no
service-principal auth involved. So this app talks to Core with a plain httpx
client, not the SDK's ``SignedCoreClient`` — the same split the Ideation Engine's
admin app documents.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from biffo_plugin_sdk import ForwardedUser, require_group
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

require_admin = require_group("admin")

_CORE_API_URL = os.environ.get("BIFFO_CORE_API_URL", "")
_PLUGIN_NAME = "idea-scout"

# How long to give a Core call, in seconds. Set explicitly and deliberately:
# a bare ``httpx.AsyncClient()`` carries httpx's own 5s default, which nobody
# here chose, and Core cold-starts in ~4.3s (init) + ~0.6s (handler) ≈ 4.9s.
# That default therefore loses a race it was never entered into — the first
# request after Core goes cold raises ``httpx.ReadTimeout`` and this app turns
# it into a 500. 30.0 matches the SDK's ``BiffoAPIClient`` default, so every
# path out of this plugin waits the same amount. See biffo-template#652.
_CORE_TIMEOUT_SECONDS = 30.0
_BUILD_TYPES_BASE = f"/api/v1/plugins/{_PLUGIN_NAME}/build-types"
_CHAT_AGENTS_BASE = f"/api/v1/admin/plugins/{_PLUGIN_NAME}/chat-agents"

app = FastAPI(title="Idea Scout Admin", docs_url=None, redoc_url=None)


async def _core_request(
    method: str, path: str, *, admin: ForwardedUser, json: dict[str, Any] | None = None
) -> Any:
    """Forward one call to Core as the calling admin — not as this plugin's
    service principal (see the module docstring)."""
    url = f"{_CORE_API_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=_CORE_TIMEOUT_SECONDS) as client:
        resp = await client.request(
            method, url, json=json, headers={"Authorization": f"Bearer {admin.token}"}
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json() if resp.content else None


# ── Build types ──────────────────────────────────────────────────────────────
#
# The categories a founder picks from. Admin-managed rather than a fixed enum so
# the list can change without a release — which is also why deactivating is
# preferred to deleting: a run stores the `key` it was started for, and deleting
# a category orphans that reference.


@app.get("/build-types")
async def list_build_types(admin: ForwardedUser = Depends(require_admin)) -> Any:
    """Every category including inactive ones — the admin view, unlike the
    founder-facing list which shows only what is currently offered."""
    return await _core_request("GET", _BUILD_TYPES_BASE, admin=admin)


@app.post("/build-types", status_code=201)
async def create_build_type(
    body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("POST", _BUILD_TYPES_BASE, admin=admin, json=body)


@app.get("/build-types/{build_type_id}")
async def read_build_type(build_type_id: str, admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", f"{_BUILD_TYPES_BASE}/{build_type_id}", admin=admin)


@app.put("/build-types/{build_type_id}")
async def update_build_type(
    build_type_id: str, body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request(
        "PUT", f"{_BUILD_TYPES_BASE}/{build_type_id}", admin=admin, json=body
    )


@app.delete("/build-types/{build_type_id}", status_code=204)
async def delete_build_type(
    build_type_id: str, admin: ForwardedUser = Depends(require_admin)
) -> None:
    """Hard-delete. Prefer setting ``active: false`` — existing runs reference
    the key, and this does not check for them."""
    await _core_request("DELETE", f"{_BUILD_TYPES_BASE}/{build_type_id}", admin=admin)


# ── Agent config ─────────────────────────────────────────────────────────────


@app.get("/chat-agents")
async def list_chat_agents(admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", _CHAT_AGENTS_BASE, admin=admin)


@app.get("/chat-agents/{agent_key}")
async def read_chat_agent(agent_key: str, admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin)


@app.put("/chat-agents/{agent_key}")
async def update_chat_agent(
    agent_key: str, body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    """Edit an agent's prompt or model.

    Note for the **synthesis** agent: the orchestration engine fires it from the
    fan-in workflow's ``action_config``, not from this row, so editing here does
    not change what synthesis runs. The workflow definition is the live copy —
    see ``scripts/seed_agent_config.py``.
    """
    return await _core_request("PUT", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin, json=body)


# ── Static admin UI ──────────────────────────────────────────────────────────
#
# Mounted last so it never shadows the API routes above. Absent in a source
# checkout (web-admin/dist is a build artifact), so the mount is conditional —
# an unbuilt UI must not stop the admin API from serving.
_DIST = Path(__file__).resolve().parent.parent.parent / "web-admin" / "dist"
if _DIST.is_dir():  # pragma: no cover — depends on a build having run
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="admin-ui")
