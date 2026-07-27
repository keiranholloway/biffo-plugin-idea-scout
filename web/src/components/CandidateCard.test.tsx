import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CandidateCard } from './CandidateCard'
import type { Candidate } from '../lib/api'

const axis = (score: number) => ({ score, rationale: `because ${score}` })

const CANDIDATE: Candidate = {
  id: 'c1',
  rank: 1,
  title: 'Compliance tooling for small brokers',
  pitch: 'A narrow tool for a regulated niche.',
  scorecard: {
    viability: axis(4),
    complexity: axis(3),
    economic_moat: axis(2),
    market_fit: axis(5),
    build_vs_buy: 'Build — nothing existing fits.',
    competitors: [{ name: 'Acme', url: 'https://acme.test', note: 'Enterprise-priced.' }],
    summary: 'Worth a look.',
  },
  sources: [{ url: 'https://example.test/thread', note: 'A complaint thread.' }],
}

describe('CandidateCard', () => {
  it('shows every axis with its score and its reasoning', () => {
    // A score with no rationale is not reviewable, which is the whole point of
    // the scorecard.
    render(<CandidateCard candidate={CANDIDATE} />)

    for (const label of ['Viability', 'Build complexity', 'Economic moat', 'Market fit']) {
      expect(screen.getByText(new RegExp(label))).toBeInTheDocument()
    }
    expect(screen.getByText('because 4')).toBeInTheDocument()
  })

  it('spells out that 5 means simple to build', () => {
    // The one axis whose direction is counter-intuitive.
    render(<CandidateCard candidate={CANDIDATE} />)

    expect(screen.getByText(/5 = simple to build/)).toBeInTheDocument()
  })

  it('links the promote action to the Ideation Engine with the pitch seeded', () => {
    render(<CandidateCard candidate={CANDIDATE} />)

    const link = screen.getByRole('link', { name: /Pressure-test this/ })
    const href = link.getAttribute('href') ?? ''
    expect(href).toMatch(/^\/ideation\/\?seed=/)
    expect(new URL(href, 'https://x.test').searchParams.get('seed')).toBe(CANDIDATE.pitch)
  })

  it('renders without a scorecard rather than crashing', () => {
    // The column is nullable; a candidate stored before scoring, or from a
    // partially-malformed run, must still be readable.
    render(<CandidateCard candidate={{ ...CANDIDATE, scorecard: null }} />)

    expect(screen.getByText(CANDIDATE.title)).toBeInTheDocument()
    expect(screen.queryByText('Viability')).not.toBeInTheDocument()
  })

  it('shows competitors and evidence', () => {
    render(<CandidateCard candidate={CANDIDATE} />)

    expect(screen.getByRole('link', { name: 'Acme' })).toBeInTheDocument()
    expect(screen.getByText(/Evidence \(1\)/)).toBeInTheDocument()
  })
})
