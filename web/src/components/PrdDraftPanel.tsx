import type { ReactNode } from 'react'

import type { PrdDocument } from '../lib/api'

function List({ items }: { items?: string[] }) {
  if (items == null || items.length === 0) return <p className="muted">None yet.</p>
  return (
    <ul className="prd-list">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="prd-section">
      <h4 className="prd-section-title">{title}</h4>
      {children}
    </section>
  )
}

function Text({ value }: { value?: string }) {
  return value ? <p className="prd-text">{value}</p> : <p className="muted">None yet.</p>
}

/** Renders every section of a stored PRD, in the estate's heading order. */
export function PrdDraftPanel({ prd }: { prd: PrdDocument }) {
  const empty = <p className="muted">None yet.</p>
  return (
    <div className="prd-draft" aria-label="PRD draft">
      <Section title="Summary">
        <Text value={prd.summary} />
      </Section>
      <Section title="Problem">
        <Text value={prd.problem} />
      </Section>
      <Section title="Goals">
        <List items={prd.goals} />
      </Section>
      <Section title="Non-Goals">
        <List items={prd.non_goals} />
      </Section>
      <Section title="Personas">
        {prd.personas?.length
          ? prd.personas.map((p, i) => (
              <div key={i} className="prd-item">
                <strong>{p.name}</strong>
                {p.description ? <p className="prd-text">{p.description}</p> : null}
                {p.needs?.length ? <List items={p.needs} /> : null}
              </div>
            ))
          : empty}
      </Section>
      <Section title="User Stories">
        {prd.user_stories?.length
          ? prd.user_stories.map((s) => (
              <div key={s.id} className="prd-item">
                <strong>
                  {s.id}: {s.title}
                </strong>
                <p className="prd-text">
                  As a {s.as_a}, I want {s.i_want}, so that {s.so_that}.
                </p>
                {s.acceptance_criteria?.length ? <List items={s.acceptance_criteria} /> : null}
              </div>
            ))
          : empty}
      </Section>
      <Section title="Functional Requirements">
        {prd.functional_requirements?.length ? (
          <ul className="prd-list">
            {prd.functional_requirements.map((r) => (
              <li key={r.id}>
                <strong>{r.id}</strong> ({r.area}): {r.requirement}
              </li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </Section>
      <Section title="UX Surfaces">
        {prd.ux_surfaces?.length
          ? prd.ux_surfaces.map((u, i) => (
              <div key={i} className="prd-item">
                <strong>{u.name}</strong>
                {u.purpose ? <p className="prd-text">{u.purpose}</p> : null}
                {u.key_elements?.length ? <List items={u.key_elements} /> : null}
              </div>
            ))
          : empty}
      </Section>
      <Section title="Permissions">
        {prd.permissions?.length
          ? prd.permissions.map((p, i) => (
              <div key={i} className="prd-item">
                <strong>{p.role}</strong>
                {p.allowed?.length ? <p className="prd-text">Allowed: {p.allowed.join('; ')}</p> : null}
                {p.denied?.length ? <p className="prd-text">Denied: {p.denied.join('; ')}</p> : null}
              </div>
            ))
          : empty}
      </Section>
      <Section title="Data Model Alignment">
        {prd.data_model?.length
          ? prd.data_model.map((e, i) => (
              <div key={i} className="prd-item">
                <strong>{e.entity}</strong>
                {e.fields?.length ? <p className="prd-text">Fields: {e.fields.join(', ')}</p> : null}
                {e.relationships?.length ? (
                  <p className="prd-text">Relationships: {e.relationships.join(', ')}</p>
                ) : null}
                {e.notes ? <p className="prd-text">{e.notes}</p> : null}
              </div>
            ))
          : empty}
      </Section>
      <Section title="API Expectations">
        <List items={prd.api_expectations} />
      </Section>
      <Section title="Events And Audit">
        <List items={prd.events_and_audit} />
      </Section>
      <Section title="Success Metrics">
        <List items={prd.success_metrics} />
      </Section>
      <Section title="Edge Cases">
        <List items={prd.edge_cases} />
      </Section>
      <Section title="Open Questions">
        <List items={prd.open_questions} />
      </Section>
      <Section title="Sources">
        {prd.sources?.length ? (
          <ul className="prd-list">
            {prd.sources.map((s, i) => (
              <li key={i}>
                {s.url}
                {s.note ? ` — ${s.note}` : ''}
              </li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </Section>
    </div>
  )
}
