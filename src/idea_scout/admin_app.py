"""Idea Scout's admin-facing ASGI app (ADR-0021 ``admin_ingress``).

**This app serves the built admin UI and built-in configuration data.**

``idea_scout_build_types`` already declares its five CRUD routes in
``biffo.plugin.json``'s ``api_routes``, so **Core** generates them and the plugin
host forwards them (biffo-template#684), authorised by the table's own
admin-only permissions. The UI calls
``/api/v1/plugins/idea-scout/build-types`` directly — one hop.

``/api/v1/admin/plugins/idea-scout/builtin-agents`` is served from here because
it returns static configuration (DEFAULT_INSTRUCTIONS, built-in models) that
the UI merges with stored rows to show a complete view — which prompts are code-defined
and which have been promoted to the database. This pattern follows ideation's
``builtin_chat_agents()`` endpoint and is necessary for the "Store a copy to edit"
button to write the real prompt rather than a placeholder.

The previous version of this file proxied CRUD routes through here with
``httpx``. Ideation documented what that costs: the host calls itself and then
forwards to Core — three hops, and a 500 when they outran the client's timeout
(biffo-template#652). We avoid that by calling Core's declared routes directly.

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

from fastapi import FastAPI
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

app = FastAPI(title="Idea Scout Admin", docs_url=None, redoc_url=None)


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


# Mounted conditionally: `web-admin/dist` is a build artefact, absent in a source
# checkout and in this app's own tests. An unbuilt UI must not stop the app
# importing — but note that a *deployed* plugin declaring `admin_ingress` with no
# `web-admin/` now fails the deploy outright (biffo-template#793), so this
# fallback can no longer hide a missing UI in production the way it did in #22.
_STATIC_DIR = _resolve_static_dir(os.environ.get("BIFFO_PLUGINS_ROOT"))
if _STATIC_DIR.is_dir():  # pragma: no cover — depends on a build having run
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="admin-ui")


@app.get("/api/v1/admin/plugins/idea-scout/builtin-agents")
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
