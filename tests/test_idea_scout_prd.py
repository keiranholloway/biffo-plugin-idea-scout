"""PRD storage, read and markdown export (#178 M2)."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from biffo_plugin_sdk import ForwardedUser
from fakes import FakeCoreGateway, candidates_message
from fastapi.testclient import TestClient

from idea_scout.app import app, get_service, require_founder
from idea_scout.definitions import (
    PRD_EMPTY_SECTION,
    ProductRequirements,
    prd_filename,
    render_prd_markdown,
    seed_config_payloads,
)
from idea_scout.models import PrdRecord
from idea_scout.service import IdeaScoutService

OWNER = "founder-a"
HEADINGS = [
    "Summary",
    "Problem",
    "Goals",
    "Non-Goals",
    "Personas",
    "Core Concepts",
    "User Stories",
    "Functional Requirements",
    "UX Surfaces",
    "Permissions",
    "Data Model Alignment",
    "API Expectations",
    "Events And Audit",
    "Success Metrics",
    "Edge Cases",
    "Open Questions",
    "Sources",
]


def _full_prd() -> ProductRequirements:
    return ProductRequirements.model_validate(
        {
            "title": "Invoice Chaser",
            "summary": "Chases late invoices.",
            "problem": "Freelancers get paid late.",
            "goals": ["Get paid faster"],
            "non_goals": ["Accounting"],
            "personas": [{"name": "Freelancer", "description": "Solo", "needs": ["Speed"]}],
            "core_concepts": [{"name": "Reminder", "description": "A nudge"}],
            "user_stories": [
                {
                    "id": "US-01",
                    "title": "Send reminder",
                    "as_a": "freelancer",
                    "i_want": "reminders",
                    "so_that": "I get paid",
                    "acceptance_criteria": ["Sent after 7 days"],
                }
            ],
            "functional_requirements": [
                {"id": "FR-01", "area": "Reminders", "requirement": "Send emails"},
                {"id": "FR-02", "area": "Billing", "requirement": "Track invoices"},
                {"id": "FR-03", "area": "Reminders", "requirement": "Schedule sends"},
            ],
            "ux_surfaces": [{"name": "Inbox", "purpose": "See invoices", "key_elements": ["List"]}],
            "permissions": [{"role": "owner", "allowed": ["all"], "denied": ["none"]}],
            "data_model": [
                {
                    "entity": "Invoice",
                    "fields": ["amount"],
                    "relationships": ["Client"],
                    "notes": "n",
                }
            ],
            "api_expectations": ["GET /invoices"],
            "events_and_audit": ["invoice.sent"],
            "success_metrics": ["DSO down"],
            "edge_cases": ["Part payment"],
            "open_questions": ["Pricing?"],
            "sources": [{"url": "https://e.com", "note": "Evidence"}],
        }
    )


def _h2(md: str) -> list[str]:
    return re.findall(r"^## (.+)$", md, flags=re.M)


def test_renderer_golden_headings_ids_and_grouping():
    md = render_prd_markdown(_full_prd())
    assert md.startswith("# PRD: Invoice Chaser\n")
    assert _h2(md) == HEADINGS
    assert "### US-01: Send reminder" in md
    assert "- **As a** freelancer" in md
    assert "- **I want** reminders" in md
    assert "- **So that** I get paid" in md
    assert "- Sent after 7 days" in md
    assert "- **FR-01**: Send emails" in md
    # grouped by area: both Reminders entries sit under one heading
    assert md.count("### Reminders") == 1
    assert md.index("FR-03") < md.index("### Billing")
    assert PRD_EMPTY_SECTION not in md


def test_empty_sections_render_none_yet_and_are_never_omitted():
    md = render_prd_markdown(ProductRequirements(title="Bare"))
    assert _h2(md) == HEADINGS
    assert md.count("_None yet._") == len(HEADINGS)


def test_filename_slug():
    assert prd_filename("Invoice Chaser!") == "prd-invoice-chaser.md"
    assert prd_filename("!!!") == "prd-untitled.md"


# ── Routes ───────────────────────────────────────────────────────────────────


@pytest.fixture
def core() -> FakeCoreGateway:
    gateway = FakeCoreGateway()
    for row in seed_config_payloads(research_model="r/m", synthesis_model="s/m"):
        gateway.configs.setdefault(
            row["role"], {"system_prompt": row["system_prompt"], "model": row["model"]}
        )
    return gateway


def _client(core: FakeCoreGateway, sub: str) -> TestClient:
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub=sub, groups=["founder"], token="tok"
    )
    app.dependency_overrides[get_service] = lambda: IdeaScoutService(
        core, research_model="r/m", synthesis_model="s/m"
    )
    return TestClient(app)


@pytest.fixture
def client(core: FakeCoreGateway) -> Iterator[TestClient]:
    yield _client(core, OWNER)
    app.dependency_overrides.clear()


def _completed_run(client: TestClient, core: FakeCoreGateway) -> str:
    run_id = client.post("/runs", json={"build_type": "micro-saas", "complexity": 3}).json()[
        "run_id"
    ]
    core.complete_all_research(run_id)
    synthesis = core.engine_fires_synthesis(run_id)
    client.get(f"/runs/{run_id}")
    synthesis.complete(candidates_message(5))
    return run_id


def _add_prd(core, run_id, candidate_id, *, status="draft", prd=None, owner=OWNER):
    core.prds.append(
        (
            owner,
            PrdRecord(
                id="prd-1",
                candidate_id=candidate_id,
                run_id=run_id,
                status=status,
                turn_count=3,
                prd=prd,
            ),
        )
    )


def test_prd_status_is_null_then_set_in_the_candidates_payload(client, core):
    run_id = _completed_run(client, core)
    cands = client.get(f"/runs/{run_id}/candidates").json()["candidates"]
    assert all("prd_status" in c and c["prd_status"] is None for c in cands)

    _add_prd(core, run_id, cands[0]["id"], status="final")
    cands = client.get(f"/runs/{run_id}/candidates").json()["candidates"]
    assert cands[0]["prd_status"] == "final"
    assert all(c["prd_status"] is None for c in cands[1:])


def test_read_prd_returns_the_row_or_404(client, core):
    run_id = _completed_run(client, core)
    cid = client.get(f"/runs/{run_id}/candidates").json()["candidates"][0]["id"]
    assert client.get(f"/candidates/{cid}/prd").status_code == 404

    _add_prd(core, run_id, cid, prd=_full_prd().model_dump())
    resp = client.get(f"/candidates/{cid}/prd")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "draft"
    assert body["candidate_id"] == cid
    assert body["turn_count"] == 3
    assert body["prd"]["title"] == "Invoice Chaser"


def test_markdown_download_headers_and_body(client, core):
    run_id = _completed_run(client, core)
    cid = client.get(f"/runs/{run_id}/candidates").json()["candidates"][0]["id"]
    # An interview with no draft yet has nothing to export.
    _add_prd(core, run_id, cid, status="interviewing", prd=None)
    assert client.get(f"/candidates/{cid}/prd.md").status_code == 404

    core.prds.clear()
    _add_prd(core, run_id, cid, prd=_full_prd().model_dump())
    resp = client.get(f"/candidates/{cid}/prd.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert resp.headers["content-disposition"] == 'attachment; filename="prd-invoice-chaser.md"'
    assert _h2(resp.text) == HEADINGS
    assert resp.text.startswith("# PRD: Invoice Chaser")


def test_another_founders_candidate_is_404_on_both_routes(client, core):
    run_id = _completed_run(client, core)
    cid = client.get(f"/runs/{run_id}/candidates").json()["candidates"][0]["id"]
    _add_prd(core, run_id, cid, prd=_full_prd().model_dump())

    other = _client(core, "founder-b")
    assert other.get(f"/candidates/{cid}/prd").status_code == 404
    assert other.get(f"/candidates/{cid}/prd.md").status_code == 404
    assert other.get("/candidates/nope/prd").status_code == 404


def test_candidate_in_a_deleted_run_is_404(client, core):
    run_id = _completed_run(client, core)
    cid = client.get(f"/runs/{run_id}/candidates").json()["candidates"][0]["id"]
    _add_prd(core, run_id, cid, prd=_full_prd().model_dump())
    client.post(f"/runs/{run_id}/delete")
    assert client.get(f"/candidates/{cid}/prd").status_code == 404
    assert client.get(f"/candidates/{cid}/prd.md").status_code == 404
