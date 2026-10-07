# Feature: Build a PRD

## Context

The owner wants every Idea Scout candidate to offer a **"Build a PRD"** action. A drafting agent works with the founder to turn everything already researched about that idea into a **full product requirements document (PRD)**. The PRD is stored against the candidate in Idea Scout's database and can be downloaded as markdown. That markdown is the input the estate's build skills (`/biffo-sibling-plan`, `/biffo-feature-plan`, and later a new-instance skill) take to stand up a Biffo instance for the idea and start building.

Owner decisions (2026-10-07):
- **Idea Scout owns the PRD.** It lives in an Idea Scout table. Ideation's Pressure Test keeps its own thin PRD unchanged.
- **Inputs:** the candidate (title, pitch, scorecard, sources), the run's raw research findings, and the founder profile snapshot.
- **Linked Pressure Test / Brain-Storm content is deferred** to a follow-up. ADR-0017 §5 says no plugin may read another plugin's tables, and nothing links an Ideation session to a candidate today.
- **Handoff is a markdown export** in the estate's PRD format. The skills already accept a local PRD file.
- **Scope is the PRD only, as an epic.** "New Biffo instance from a PRD" is a separate follow-up issue.
- **Core chat defect:** tracked as a biffo-template bug ([issue 2408](https://github.com/keiranholloway/biffo-template/issues/2408)). The interview milestone depends on it.

## Success criteria (observable)

1. Every completed candidate card shows **Build a PRD**. Once a PRD exists, the card shows **Open PRD** and the PRD's status (draft or final).
2. Starting a PRD opens a chat. The agent's opening turn shows it already knows the candidate's pitch, scorecard, sources, research findings and founder profile. It does not ask the founder to re-type them.
3. **Update draft** produces a structured PRD covering every estate section, stored in `idea_scout_prds` against the candidate. It survives leaving and returning: reopening shows the transcript and the latest draft.
4. **Mark final** sets the status to `final`. **Download markdown** returns a `.md` file whose headings match the estate's PRD format: Summary, Problem, Goals, Non-Goals, Personas, User Stories (with IDs), Functional Requirements (with IDs), UX Surfaces, Permissions, Data Model Alignment, API Expectations, Events And Audit, Success Metrics, Edge Cases, Open Questions, Sources. `/biffo-sibling-plan` reads exactly these headings.
5. Another founder's candidate or PRD returns 404 on every route.

## Scope / explicitly deferred

In scope: research-findings read, PRD storage and export, the drafting agent with interview and compile, and the founder UI. All of it is in `biffo-plugin-idea-scout`.

Deferred, each tracked as its own issue:
- **Linked Pressure Test / Brain-Storm input.** Needs an ADR-0017 §5 decision first, a source-candidate link in Ideation, and an answer on Ideation being admin-only while Idea Scout is founder-only.
- **New Biffo instance from a stored PRD.** A skill in `biffo-agent-config`. No skill wraps `biffo init` today.
- **Direct editing of PRD sections in the UI.** v1 revises through the chat followed by Update draft.

## Current state (from `origin/dev` @ `443a421`)

- **Tables:** owner-scoped tables are declared in `biffo.plugin.json` (runs, candidates, cadence) with `owner_scoped_service.allowed_principals: ["system:idea-scout"]`.
  - There is no JSON column type. JSON goes in `Text`, written with `json.dumps` and read with `adapter._load_json`.
  - Declared defaults are not applied, so post-insert columns must be nullable.
  - Core generates the migration from the manifest.
  - Owner-data has no DELETE, so rows are soft-deleted.
  - Manifest guard tests: `tests/test_idea_scout_manifest.py` (expected tables, `OWNER_SCOPED_TABLES`, `json_columns`, `EXPECTED_CAPABILITIES`).
- **Agent runs:** `adapter.request_agent_run`, `get_agent_run` → `AgentRunView`, `service._tool_call_arguments`, `extract_candidates`.
  - `extract_findings` (`service.py:171-184`) already parses the research agents' `submit_research_findings` → `FindingSet`, but **only a test calls it**. Findings are not persisted; the run keeps `research_run_ids`.
  - **Core never purges agent runs** (no TTL or retention found), so findings can be read back from the runs on demand.
- **No chat machinery in Idea Scout.** Ideation's Pressure Test is the pattern to copy:
  - `adapter.py:207-257`: `POST /internal/agent-chat/{agent_key}` with `{message, thread_id}`, and `GET /internal/agent-runs/threads/{thread_id}/messages`.
  - Async analyst run with an output tool, collected lazily when the browser polls (`service.py:253-335`).
  - `chat_agents_dynamic: true`, plus the `chat-turn` and `thread-messages-read` capabilities.
  - The web `ChatComposer` (`web/src/components/ChatComposer.tsx`).
  - Core's chat-context assemblers are Core-registered only, so a plugin **cannot** inject context into a chat turn. The dossier goes in the opening user turn, as Pressure Test does with its seed.
- **Agent config:**
  - `definitions.py`: agent name constants, `DEFAULT_INSTRUCTIONS`, `seed_config_payloads()`.
  - `app.py` and `admin_app.py` seed at startup.
  - `admin_app.builtin_agents` lists 4 agents.
  - Tests pin those sets (`test_idea_scout_definitions.py:156`, `test_idea_scout_admin_app.py:34`).
  - `service._resolve_agent` returns 502 if the config row is missing.
- **Ownership:** `service._load_owned` returns 404 for a missing or soft-deleted run. There is no candidate-level helper; Core's owner-data `GET /{id}` 404s on another owner's row.
- **Web:**
  - `App.tsx` is a single component switched on `current` (no router).
  - `CandidateCard` has one action, the "Pressure-test this" anchor.
  - The `Candidate` id is Core's row id.
  - `App.request-fanout.test.tsx` pins mount to 3 requests, so PRD presence must ride the candidates payload, not a new fetch.
- **Estate PRD format:** `tabsii-platform/docs/PRD-0001-franchise-development-crm-p1/README.md`. `/biffo-sibling-plan` Step 1 reads Functional Requirements, User Stories, API Expectations, UX Surfaces, Permissions and Data Model Alignment.
- **Core chat defect (code-traced, not live-confirmed; [biffo-template issue 2408](https://github.com/keiranholloway/biffo-template/issues/2408)):** `agent_chat_service.run_chat_turn` stores each run's *full* assembled transcript. The next turn builds `prior_messages` by concatenating every prior run's stored messages (`agent_chat_service.py` ~70-77), and `chat_engine.thread_history` doesn't dedupe. History therefore repeats earlier turns and the repetition compounds, and `max_history_messages` (default 40) truncates real content early. `GET /internal/agent-runs/threads/{id}/messages` joins the same duplicates. A long PRD interview depends on this.

## Cross-repo boundary

All milestones are in `keiranholloway/biffo-plugin-idea-scout`, a plugin repo with no `core-manifest.json` split. The Core chat fix is template-owned (`services/api/src/api/agent_chat_service.py` and `chat_engine.py` in `biffo-template`) and is tracked there ([issue 2408](https://github.com/keiranholloway/biffo-template/issues/2408)), not as a milestone here. Reaching dev needs the usual biffo-platform plugin resync, which the fleet owns.

## PRD schema (shared reference for M2 to M4)

`ProductRequirements` (pydantic, `definitions.py`), stored as JSON text:
- `title`, `summary`, `problem`
- `goals[]`, `non_goals[]`
- `personas[{name, description, needs[]}]`
- `core_concepts[{name, description}]`
- `user_stories[{id: "US-01", title, as_a, i_want, so_that, acceptance_criteria[]}]`
- `functional_requirements[{id: "FR-01", area, requirement}]`
- `ux_surfaces[{name, purpose, key_elements[]}]`
- `permissions[{role, allowed[], denied[]}]`
- `data_model[{entity, fields[], relationships[], notes}]`
- `api_expectations[]`, `events_and_audit[]`, `success_metrics[]`, `edge_cases[]`, `open_questions[]`
- `sources[{url, note}]`

Markdown renders as `# PRD: <title>` with `##` headings in the order listed in success criterion 4.

## Milestones

**M1: Read a run's research findings.**
- Add `GET /runs/{run_id}/research`, owner-checked through `_load_owned`.
- For each research run it returns `{angle, status: succeeded|failed|never_started|malformed, findings[]}`, read via `get_agent_run` + `extract_findings`.
- Add a service method `get_research(owner_sub, run_id)` that M3 reuses.
- Pre-merge: tests for one fixture per status; 404 for another owner and for a soft-deleted run; fakes shaped from Core's real `GET /internal/agent-runs/{id}` response.
- Verified after merge: on dev, a completed run returns findings for all three angles.

**M2: PRD storage, read and markdown export.**
- New owner-scoped table `idea_scout_prds`: `owner_sub`, `candidate_id`, `run_id`, `status` (`interviewing|drafting|draft|final|failed`), `thread_id`, `turn_count`, `compile_run_id`, `prd` (Text JSON), `failure_reason`, `deleted`. Post-insert columns are nullable.
- Add `ProductRequirements` and a pure `render_prd_markdown()`.
- Add `GET /candidates/{id}/prd` (404 if none) and `GET /candidates/{id}/prd.md` (`text/markdown`, `Content-Disposition: attachment; filename=prd-<slug>.md`).
- Add `prd_status` (null or status) to each candidate in `GET /runs/{id}/candidates`.
- Add a candidate-ownership helper.
- Update the manifest guard tests.
- Pre-merge:
  - a renderer golden test asserting every heading;
  - route tests: read, markdown, 404 cross-owner, `prd_status` present;
  - the fan-out test is still 3.
- Verified after merge: the table exists on dev after resync.

**M3: PRD interview chat (backend).**
- Register agent `idea-scout-prd-interviewer`: constant, prompt, model, seed row, `builtin_agents` entry, manifest `chat_agents_dynamic: true` plus the `chat-turn` and `thread-messages-read` capabilities. Update the pinned agent-count tests.
- Add `POST /candidates/{id}/prd`. It creates the PRD row, or resumes it if one exists, and runs turn 1 with a dossier opening message: candidate, scorecard, sources, M1 findings and the run's `profile_snapshot`.
- Add `POST /prds/{id}/messages` and `GET /prds/{id}/messages`, ported from Ideation's chat path.
- Turn cap `PRD_MAX_TURNS = 15`, which keeps the whole interview inside `max_history_messages` so the dossier is never truncated.
- Depends on [biffo-template issue 2408](https://github.com/keiranholloway/biffo-template/issues/2408) being merged and synced.
- Pre-merge: tests that the dossier contains each input, the cap returns 409, cross-owner returns 404, and the transcript round-trips.
- Verified after merge: a live 5+ turn interview on dev whose transcript has no repeated turns.

**M4: Compile the draft (backend).**
- Add `POST /prds/{id}/draft`, which requests an async run of `idea-scout-prd-writer` with output tool `submit_prd` (schema `ProductRequirements`) and `input_payload = {dossier, conversation, previous_draft}`. Status becomes `drafting`.
- The read path collects it lazily, as Ideation's `get_report` does: it stores `prd` and sets status `draft`. Malformed output or a failed run sets status `failed`, keeping any previous draft.
- Add `POST /prds/{id}/finalise`, which goes `draft` → `final`. Further chat or a new draft moves it back to `draft`.
- Pre-merge: tests for the happy path, malformed output, a failed run, a re-draft that keeps the previous draft, and the finalise transitions.
- Verified after merge: on dev, a compiled PRD whose downloaded markdown has every heading.

**M5: Founder UI: open the PRD workspace and chat.**
- `CandidateCard` gets **Build a PRD** / **Open PRD (draft|final)**, driven by `prd_status`.
- A PRD view in `App.tsx` (a `current`-style switch) holds the transcript, a `ChatComposer` (copied from Ideation) and a back link to the run.
- Every new CSS class is defined in `index.css`.
- Pre-merge: vitest for the card states, starting and resuming, sending a turn, the cap, and the 3-request fan-out.
- Verified after merge: a click-through on dev.

**M6: Founder UI: draft panel, finalise and download.**
- A draft panel rendering every section, an **Update draft** button with polling while `drafting`, **Mark final**, **Download markdown** (from `/prd.md`), and failed/retry states.
- Pre-merge: vitest for each status and an assertion on the download link.
- Verified after merge: on dev, build a PRD end to end, download the `.md`, and confirm `/biffo-sibling-plan` accepts it as a local PRD.

Dependency order: M1 → M2 → M3 (also waits on the template bug) → M4 → M5 → M6. The plugin's domain sits in a few files (`service.py`, `app.py`, `adapter.py`, the manifest), so the milestones overlap in what they read. They run in sequence, not in parallel.

## Testing plan

- pytest for each milestone, using `FakeCoreGateway` / `FakeTransport` shaped from real Core responses, not from what the code emits.
- vitest for M5 and M6, plus the fan-out guard.
- End to end after merge, fleet-owned: on dev, run a scout → Build a PRD → 5+ turns → Update draft → Mark final → Download → feed it to `/biffo-sibling-plan` as a local file.

## Rollout

Each milestone reaches dev through the usual biffo-platform resync of this plugin. The PRD interview (M3) can't be verified live until the Core chat-history fix ([biffo-template issue 2408](https://github.com/keiranholloway/biffo-template/issues/2408)) is merged and the platform has taken the core upgrade.
