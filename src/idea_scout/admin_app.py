"""Idea Scout's admin-facing ASGI app (ADR-0021 ``admin_ingress``).

**This app serves the built admin UI and nothing else.** It deliberately has no
API routes, and that is the whole design:

``idea_scout_build_types`` already declares its five CRUD routes in
``biffo.plugin.json``'s ``api_routes``, so **Core** generates them and the plugin
host forwards them (biffo-template#684), authorised by the table's own
admin-only permissions. The UI calls
``/api/v1/plugins/idea-scout/build-types`` directly — one hop.

The previous version of this file proxied those same routes through here with
``httpx``. Ideation documented what that costs: the host calls itself and then
forwards to Core — three hops, and a 500 when they outran the client's timeout
(biffo-template#652). There is no reason to pay that for routes Core already
serves.

Reinstated after biffo-plugin-idea-scout#22, which removed the previous
declaration because it promised a UI that did not exist. Both defects that issue
identified are fixed here: there is now a real ``web-admin/`` tree, and the
static path is resolved from ``BIFFO_PLUGINS_ROOT`` rather than from
``__file__``.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Idea Scout Admin", docs_url=None, redoc_url=None)


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
