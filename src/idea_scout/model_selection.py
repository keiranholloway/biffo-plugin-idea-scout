"""One model for every Idea Scout agent.

The admin picks one **base** model id from the curated catalog. Which agents
search the web is decided in code (``definitions.AGENT_WEB_SEARCH``), so each
agent's *effective* model is ``effective_model(base, agent)``.

The catalog's single active ``is_default`` row is the selected model. Research
and PRD-writer runs read it directly; synthesis (Core's fan-in workflow) and the
PRD interviewer (a Core chat turn) read their stored agent rows, so applying a
selection also writes every agent's effective model into its row.

This module is transport-agnostic: it talks to a :class:`ModelBackend`, which the
admin app binds to the calling admin's token and the startup path binds to the
plugin's service principal. Tests bind a fake that records the writes.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .definitions import (
    AGENT_WEB_SEARCH,
    ALL_AGENT_NAMES,
    CURATED_MODELS,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_SELECTED_MODEL,
    LEGACY_SYNTHESIS_PROMPT_MARKER,
    SYNTHESIS_AGENT_NAME,
    InvalidBaseModelError,
    effective_model,
    seed_config_payloads,
    validate_base_model,
)

_LOGGER = logging.getLogger(__name__)


class ModelSelectionError(Exception):
    """The requested model cannot be selected (maps to HTTP 422)."""


class ModelBackend(Protocol):
    async def list_catalog(self) -> list[dict[str, Any]]:
        """Every catalog row (active or not): id, model_id, label, active, is_default."""
        ...

    async def create_catalog(self, row: dict[str, Any]) -> None: ...

    async def update_catalog(self, row_id: str, fields: dict[str, Any]) -> None: ...

    async def get_agent_models(self) -> dict[str, str | None]:
        """``{agent_key: stored model}`` for the agent rows that exist."""
        ...

    async def seed_agents(self, payloads: list[dict[str, Any]]) -> None:
        """Create the given agent rows where absent. Never overwrites."""
        ...

    async def set_agent_model(self, agent_key: str, model: str) -> None: ...

    async def get_agent_prompts(self) -> dict[str, str]:
        """``{agent_key: stored system prompt}`` for the agent rows that exist."""
        ...

    async def set_agent_prompt(self, agent_key: str, prompt: str) -> None: ...


def _is_active(row: dict[str, Any]) -> bool:
    return bool(row.get("active"))


def _is_base(row: dict[str, Any]) -> bool:
    return ":" not in str(row.get("model_id", ""))


def selectable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Catalog rows that may be offered: active, base id."""
    return sorted(
        (r for r in rows if _is_active(r) and _is_base(r)),
        key=lambda r: (str(r.get("label", "")), str(r.get("model_id", ""))),
    )


def selected_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The single active base-id default row, or None."""
    return next((r for r in selectable(rows) if r.get("is_default")), None)


def selected_base_model(rows: list[dict[str, Any]]) -> str:
    """The selected base model id, falling back to the built-in default."""
    row = selected_row(rows)
    return str(row["model_id"]) if row else DEFAULT_SELECTED_MODEL


def effective_models(base: str) -> dict[str, str]:
    return {name: effective_model(base, name) for name in ALL_AGENT_NAMES}


async def seed_catalog(backend: ModelBackend) -> None:
    """Insert the curated list where absent; deactivate legacy ``:`` rows."""
    rows = await backend.list_catalog()
    have = {str(r.get("model_id")) for r in rows}
    for model in CURATED_MODELS:
        if model["model_id"] in have:
            continue
        await backend.create_catalog(
            {
                "model_id": model["model_id"],
                "label": model["label"],
                "active": True,
                "is_default": False,
            }
        )
    for row in rows:
        if not _is_base(row) and (_is_active(row) or row.get("is_default")):
            await backend.update_catalog(str(row["id"]), {"active": False, "is_default": False})


async def _write_agents(backend: ModelBackend, base: str) -> dict[str, str]:
    wanted = effective_models(base)
    stored = await backend.get_agent_models()
    absent = [n for n in ALL_AGENT_NAMES if n not in stored]
    if absent:
        payloads = seed_config_payloads(
            research_model=wanted[ALL_AGENT_NAMES[0]],
            synthesis_model=wanted["idea-scout-synthesis"],
            interviewer_model=wanted["idea-scout-prd-interviewer"],
            writer_model=wanted["idea-scout-prd-writer"],
        )
        for payload in payloads:
            payload["model"] = wanted[payload["agent_key"]]
        await backend.seed_agents([p for p in payloads if p["agent_key"] in absent])
    for name in ALL_AGENT_NAMES:
        if stored.get(name) != wanted[name]:
            await backend.set_agent_model(name, wanted[name])
    await _refresh_stale_synthesis_prompt(backend)
    return wanted


async def _refresh_stale_synthesis_prompt(backend: ModelBackend) -> None:
    """Replace a stored synthesis prompt that still asks for the whole candidate set.

    Seeding is insert-if-absent, so a deployment seeded before the ranking/
    write-up split keeps the old prompt, and Core's fan-in runs synthesis from
    that stored row. The old prompt asks for rationales, competitors and sources
    for every idea (10k+ output tokens) against a ranking-only schema, which is
    the 240s wall-clock failure. Only a prompt carrying the legacy marker is
    replaced; an admin's own edit of the new prompt is left alone.
    """
    get = getattr(backend, "get_agent_prompts", None)
    put = getattr(backend, "set_agent_prompt", None)
    if get is None or put is None:
        return
    prompt = (await get()).get(SYNTHESIS_AGENT_NAME)
    if prompt is not None and LEGACY_SYNTHESIS_PROMPT_MARKER in prompt:
        _LOGGER.warning("Replacing the stale full-candidate-set synthesis prompt")
        await put(SYNTHESIS_AGENT_NAME, DEFAULT_INSTRUCTIONS[SYNTHESIS_AGENT_NAME])


async def apply_selection(backend: ModelBackend, model_id: str) -> str:
    """``PUT /model``: validate, make ``model_id`` the only default, write rows.

    Nothing is written when validation fails.
    """
    try:
        validate_base_model(model_id)
    except InvalidBaseModelError as exc:
        raise ModelSelectionError(str(exc)) from exc
    rows = await backend.list_catalog()
    target = next((r for r in selectable(rows) if r.get("model_id") == model_id), None)
    if target is None:
        raise ModelSelectionError(f"{model_id!r} is not an active model in the catalog.")
    await _set_only_default(backend, rows, str(target["id"]))
    await _write_agents(backend, model_id)
    return model_id


async def _set_only_default(backend: ModelBackend, rows: list[dict[str, Any]], row_id: str) -> None:
    for row in rows:
        if row.get("is_default") and str(row["id"]) != row_id:
            await backend.update_catalog(str(row["id"]), {"is_default": False})
    for row in rows:
        if str(row["id"]) == row_id and not row.get("is_default"):
            await backend.update_catalog(row_id, {"is_default": True})


async def describe(backend: ModelBackend) -> dict[str, Any]:
    """``GET /model``: the selection, the options, and each agent's models."""
    rows = await backend.list_catalog()
    base = selected_base_model(rows)
    stored = await backend.get_agent_models()
    agents = []
    for name in ALL_AGENT_NAMES:
        want = effective_model(base, name)
        have = stored.get(name)
        agents.append(
            {
                "agent_key": name,
                "effective_model": want,
                "stored_model": have,
                "web_search": AGENT_WEB_SEARCH[name],
                "stored": name in stored,
                "drift": name in stored and have != want,
            }
        )
    return {
        "selected_model_id": base,
        "options": [
            {"id": r["id"], "model_id": r["model_id"], "label": r["label"]}
            for r in selectable(rows)
        ],
        "agents": agents,
    }


async def effective_for_agent(backend: ModelBackend, agent_key: str) -> str | None:
    """The model ``agent_key`` must carry, or None for an unknown agent."""
    if agent_key not in AGENT_WEB_SEARCH:
        return None
    rows = await backend.list_catalog()
    return effective_model(selected_base_model(rows), agent_key)


async def reconcile(backend: ModelBackend) -> str:
    """Startup: seed the catalog, ensure a default exists, rewrite agent rows."""
    await seed_catalog(backend)
    rows = await backend.list_catalog()
    row = selected_row(rows)
    if row is None:
        target = next(
            (r for r in selectable(rows) if r.get("model_id") == DEFAULT_SELECTED_MODEL), None
        )
        if target is None:
            raise ModelSelectionError(f"{DEFAULT_SELECTED_MODEL!r} is missing from the catalog.")
        await _set_only_default(backend, rows, str(target["id"]))
        base = DEFAULT_SELECTED_MODEL
    else:
        base = str(row["model_id"])
        # More than one default is repaired to exactly one.
        extras = [r for r in selectable(rows) if r.get("is_default") and r["id"] != row["id"]]
        for extra in extras:
            await backend.update_catalog(str(extra["id"]), {"is_default": False})
    await _write_agents(backend, base)
    return base


# ── HTTP binding ─────────────────────────────────────────────────────────────

_WRITE_DROP = ("id", "created_at", "updated_at", "tenant_id")


class RequestBackend:
    """A :class:`ModelBackend` over a ``request(method, path, json=...)`` callable.

    Two shapes share it:

    - **admin** (``seed_path=None``): agent rows are the admin chat-agents list,
      absent rows are created with ``POST``; the caller's own token authorises.
    - **startup** (``seed_path`` set): agent rows are read one role at a time and
      absent ones go through the insert-if-absent seed route, as the plugin's
      service principal.
    """

    def __init__(
        self,
        request: Any,
        *,
        catalog_path: str,
        agents_path: str,
        seed_path: str | None = None,
        not_found: type[Exception] = LookupError,
    ) -> None:
        self._request = request
        self._catalog = catalog_path
        self._agents = agents_path
        self._seed = seed_path
        self._not_found = not_found
        self._rows: dict[str, dict[str, Any]] = {}

    async def list_catalog(self) -> list[dict[str, Any]]:
        return list(await self._request("GET", self._catalog) or [])

    async def create_catalog(self, row: dict[str, Any]) -> None:
        await self._request("POST", self._catalog, json=row)

    async def update_catalog(self, row_id: str, fields: dict[str, Any]) -> None:
        current = next((r for r in await self.list_catalog() if str(r["id"]) == row_id), None)
        body = {k: v for k, v in (current or {}).items() if k not in _WRITE_DROP}
        body.update(fields)
        await self._request("PUT", f"{self._catalog}/{row_id}", json=body)

    async def get_agent_models(self) -> dict[str, str | None]:
        found: dict[str, dict[str, Any]] = {}
        if self._seed is None:
            for row in await self._request("GET", self._agents) or []:
                found[str(row.get("agent_key"))] = row
        else:
            for name in ALL_AGENT_NAMES:
                try:
                    row = await self._request("GET", f"{self._agents}/{name}")
                except self._not_found:
                    continue
                if row:
                    found[name] = {"agent_key": name, **row}
        self._rows = found
        return {k: v.get("model") for k, v in found.items()}

    async def seed_agents(self, payloads: list[dict[str, Any]]) -> None:
        if self._seed is not None:
            await self._request("POST", self._seed, json=payloads)
        else:
            for payload in payloads:
                await self._request("POST", self._agents, json=payload)
        self._rows = {}

    async def get_agent_prompts(self) -> dict[str, str]:
        if not self._rows:
            await self.get_agent_models()
        return {k: str(v["system_prompt"]) for k, v in self._rows.items() if v.get("system_prompt")}

    async def set_agent_prompt(self, agent_key: str, prompt: str) -> None:
        row = self._rows.get(agent_key)
        if row is None:
            row = await self._request("GET", f"{self._agents}/{agent_key}") or {}
        body = {k: v for k, v in row.items() if k not in _WRITE_DROP}
        body.update({"agent_key": agent_key, "system_prompt": prompt})
        await self._request("PUT", f"{self._agents}/{agent_key}", json=body)
        self._rows[agent_key] = {**row, "system_prompt": prompt}

    async def set_agent_model(self, agent_key: str, model: str) -> None:
        row = self._rows.get(agent_key)
        if row is None:
            row = await self._request("GET", f"{self._agents}/{agent_key}") or {}
        body = {k: v for k, v in row.items() if k not in _WRITE_DROP}
        body.update({"agent_key": agent_key, "model": model})
        await self._request("PUT", f"{self._agents}/{agent_key}", json=body)
        self._rows[agent_key] = {**row, "model": model}
