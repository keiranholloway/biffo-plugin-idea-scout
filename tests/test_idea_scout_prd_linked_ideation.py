"""PRD dossier includes linked Pressure Test / Brain-Storm content (#180)."""
# ruff: noqa: F811

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fakes import FakeTransport
from test_idea_scout_prd_chat import (  # noqa: F401  (fixtures)
    OTHER,
    OWNER,
    candidate_id,
    client,
    core,
)

from idea_scout.adapter import (
    _IDEATION_BRAINSTORMS,
    _IDEATION_OPPORTUNITIES,
    _IDEATION_REPORTS,
    _IDEATION_SESSIONS,
    CoreHttpError,
    CoreHttpGateway,
    CoreNotFoundError,
)

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


_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ideation_owner_data.json").read_text())


def _rows(**override):
    return {
        ("GET", path): override.get(name, _FIXTURE[name])
        for name, path in (
            ("ideation_sessions", _IDEATION_SESSIONS),
            ("ideation_reports", _IDEATION_REPORTS),
            ("brainstorm_sessions", _IDEATION_BRAINSTORMS),
            ("brainstorm_opportunities", _IDEATION_OPPORTUNITIES),
        )
    }


def _read(responses, owner="alice"):
    t = FakeTransport(responses)
    got = asyncio.run(
        CoreHttpGateway(t).get_linked_ideation(owner_sub=owner, candidate_id="cand-1")
    )
    return got, t


def test_adapter_reads_ideation_rows_shaped_like_the_real_tables():
    got, t = _read(_rows())
    assert got is not None
    assert got["report"]["thin_prd"] == {"problem": "PRESSURE-THIN-PRD-MARK"}
    assert got["research"]["findings"][0]["findings"] == ["BRAINSTORM-RESEARCH-MARK"]
    assert [o["title"] for o in got["research"]["opportunities"]] == ["First", "Second"]
    assert t.last("GET", _IDEATION_SESSIONS)["params"] == {"source_candidate_id": "cand-1"}
    assert t.last("GET", _IDEATION_REPORTS)["params"] == {"session_id": "s1"}


def test_adapter_drops_another_owners_rows_core_returned():
    got, _ = _read(_rows(), owner="mallory")
    assert got is None


def test_adapter_drops_rows_linked_to_another_candidate_or_deleted():
    sessions = [
        {**_FIXTURE["ideation_sessions"][0], "source_candidate_id": "other"},
        {**_FIXTURE["ideation_sessions"][0], "deleted": True},
    ]
    brains = [{**_FIXTURE["brainstorm_sessions"][0], "deleted": True}]
    got, _ = _read(_rows(ideation_sessions=sessions, brainstorm_sessions=brains))
    assert got is None


def test_adapter_keeps_only_the_callers_report_and_opportunity_rows():
    reports = [{**_FIXTURE["ideation_reports"][0], "owner_sub": "mallory"}]
    opps = [{**o, "owner_sub": "mallory"} for o in _FIXTURE["brainstorm_opportunities"]]
    got, _ = _read(
        _rows(
            ideation_reports=reports,
            brainstorm_opportunities=opps,
            brainstorm_sessions=[{**_FIXTURE["brainstorm_sessions"][0], "research_findings": None}],
        )
    )
    assert got is None


def test_adapter_returns_only_the_present_half():
    got, _ = _read(_rows(brainstorm_sessions=[]))
    assert got is not None and set(got) == {"report"}


def test_adapter_maps_errors_and_junk_to_none():
    for resp in (CoreNotFoundError("x"), CoreHttpError("403"), RuntimeError("net")):

        class Raising(FakeTransport):
            async def request(self, method, path, *, _err=resp, **kw):
                raise _err

        got = asyncio.run(
            CoreHttpGateway(Raising()).get_linked_ideation(owner_sub="alice", candidate_id="c")
        )
        assert got is None
    for junk in ({}, None, ["x"], "x"):
        got, _ = _read({k: junk for k in _rows()})
        assert got is None


def test_ideation_grant_is_declared_by_ideation_not_idea_scout():
    # The read is authorised by Ideation's ``allowed_principals`` (see
    # tests/fixtures/ideation_owner_data.json provenance). Idea Scout declares no
    # table for it, and must not widen its own tables to do so.
    manifest = json.loads((Path(__file__).parent.parent / "biffo.plugin.json").read_text())
    own = {t["name"] for t in manifest["tables"]}
    assert not own & {"ideation_sessions", "ideation_reports", "brainstorm_sessions"}
