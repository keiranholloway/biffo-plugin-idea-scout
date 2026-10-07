"""PRD dossier includes linked Pressure Test / Brain-Storm content (#180)."""
# ruff: noqa: F811

from __future__ import annotations

import asyncio

from fakes import FakeTransport
from test_idea_scout_prd_chat import (  # noqa: F401  (fixtures)
    OTHER,
    OWNER,
    candidate_id,
    client,
    core,
)

from idea_scout.adapter import _LINKED_IDEATION, CoreHttpError, CoreHttpGateway, CoreNotFoundError

LINKED = {
    "report": {"scorecard": {"verdict": "go"}, "thin_prd": "PRESSURE-THIN-PRD-MARK"},
    "research": {"summary": "BRAINSTORM-RESEARCH-MARK"},
}


def _dossier(core) -> str:
    return core.chat_turns[0]["message"]


def test_dossier_contains_linked_content_when_present(client, core, candidate_id):
    core.ideation[candidate_id] = (OWNER, LINKED)
    client.post(f"/candidates/{candidate_id}/prd")
    d = _dossier(core)
    assert "## Pressure Test report" in d and "PRESSURE-THIN-PRD-MARK" in d
    assert "## Brain-Storm research" in d and "BRAINSTORM-RESEARCH-MARK" in d


def test_dossier_omits_sections_when_nothing_linked(client, core, candidate_id):
    assert client.post(f"/candidates/{candidate_id}/prd").status_code == 200
    d = _dossier(core)
    assert "Pressure Test" not in d and "Brain-Storm" not in d


def test_partial_content_only_adds_that_section(client, core, candidate_id):
    core.ideation[candidate_id] = (OWNER, {"research": LINKED["research"]})
    client.post(f"/candidates/{candidate_id}/prd")
    d = _dossier(core)
    assert "## Brain-Storm research" in d and "Pressure Test report" not in d


def test_ideation_error_does_not_block_the_prd(client, core, candidate_id):
    core.ideation[candidate_id] = (OWNER, LINKED)
    core.ideation_error = True
    resp = client.post(f"/candidates/{candidate_id}/prd")
    assert resp.status_code == 200 and resp.json()["turn_count"] == 1
    assert "PRESSURE-THIN-PRD-MARK" not in _dossier(core)


def test_a_raising_gateway_does_not_block_the_prd(client, core, candidate_id):
    async def boom(**_):
        raise RuntimeError("ideation down")

    core.get_linked_ideation = boom  # type: ignore[method-assign]
    assert client.post(f"/candidates/{candidate_id}/prd").status_code == 200


def test_another_owners_ideation_data_is_never_included(client, core, candidate_id):
    core.ideation[candidate_id] = (OTHER, LINKED)
    client.post(f"/candidates/{candidate_id}/prd")
    assert "PRESSURE-THIN-PRD-MARK" not in _dossier(core)
    assert core.ideation_reads == [(OWNER, candidate_id)]


def _gateway(response):
    if isinstance(response, Exception):

        class Raising(FakeTransport):
            async def request(self, method, path, **kw):
                raise response

        return CoreHttpGateway(Raising())
    return CoreHttpGateway(FakeTransport({("GET", _LINKED_IDEATION): response}))


def test_adapter_returns_linked_content():
    got = asyncio.run(
        _gateway({**LINKED, "ignored": 1}).get_linked_ideation(owner_sub="o", candidate_id="c")
    )
    assert got == LINKED


def test_adapter_maps_errors_and_empty_to_none():
    for resp in (
        CoreNotFoundError("x"),
        CoreHttpError("403"),
        RuntimeError("net"),
        {},
        None,
        ["x"],
    ):
        got = asyncio.run(_gateway(resp).get_linked_ideation(owner_sub="o", candidate_id="c"))
        assert got is None
