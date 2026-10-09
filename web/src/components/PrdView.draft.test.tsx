import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createApi, type PrdFull, type PrdStatus } from '../lib/api'
import { PrdView } from './PrdView'

const CAND = { id: 'c1', rank: 1, title: 'Broker tooling', pitch: 'p', scorecard: null, sources: [] }

const DOC = {
  title: 'Broker tooling',
  summary: 'A summary body.',
  problem: 'A problem body.',
  goals: ['Goal one'],
  user_stories: [
    { id: 'US-01', title: 'Quote', as_a: 'broker', i_want: 'quotes', so_that: 'I win' },
  ],
  functional_requirements: [{ id: 'FR-01', area: 'Quotes', requirement: 'Generate quotes' }],
}

function row(status: PrdStatus, over: Partial<PrdFull> = {}): PrdFull {
  return {
    id: 'p1',
    candidate_id: 'c1',
    run_id: 'r1',
    status,
    thread_id: 't1',
    turn_count: 3,
    compile_run_id: null,
    prd: null,
    failure_reason: null,
    ...over,
  }
}

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>
let handler: Handler
const calls: { url: string; method: string; auth: string | null }[] = []

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mountWith(prds: PrdFull[]) {
  // GET /prds/p1 returns each row in turn, then the last one repeatedly.
  let i = 0
  handler = (url, init) => {
    const method = init.method ?? 'GET'
    if (url.endsWith('/candidates/c1/prd') && method === 'POST')
      return json({ ...row('interviewing'), max_turns: 15, messages: [{ role: 'assistant', content: 'Hello' }] })
    if (url.endsWith('/prds/p1') && method === 'GET') return json(prds[Math.min(i++, prds.length - 1)])
    if (url.endsWith('/prds/p1/draft')) return json(row('drafting'))
    if (url.endsWith('/prds/p1/finalise')) return json(row('final', { prd: DOC }))
    if (url.endsWith('/prd.md'))
      return new Response('# md', {
        headers: { 'Content-Disposition': 'attachment; filename="broker-tooling.md"' },
      })
    return json({}, 404)
  }
  const api = createApi(() => 'tok')
  return render(<PrdView api={api} candidate={CAND} onBack={() => undefined} />)
}

beforeEach(() => {
  calls.length = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const headers = (init.headers ?? {}) as Record<string, string>
      calls.push({ url, method: init.method ?? 'GET', auth: headers.Authorization ?? null })
      return handler(url, init)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('PRD draft panel', () => {
  it('interviewing with no draft: Update draft, no Mark final or download', async () => {
    mountWith([row('interviewing')])
    await screen.findByText('Hello')
    expect(await screen.findByText(/No draft yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Update draft' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Mark final' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Download markdown' })).toBeNull()
  })

  it('draft: renders every section and offers Mark final, which calls finalise', async () => {
    mountWith([row('draft', { prd: DOC })])
    expect(await screen.findByText('A summary body.')).toBeInTheDocument()
    for (const h of [
      'Summary', 'Problem', 'Goals', 'Non-Goals', 'Personas', 'User Stories',
      'Functional Requirements', 'UX Surfaces', 'Permissions', 'Data Model Alignment',
      'API Expectations', 'Events And Audit', 'Success Metrics', 'Edge Cases',
      'Open Questions', 'Sources',
    ])
      expect(screen.getByRole('heading', { name: h })).toBeInTheDocument()
    expect(screen.getByText(/US-01: Quote/)).toBeInTheDocument()
    expect(screen.getByText('FR-01')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Mark final' }))
    expect(await screen.findByText('This PRD is final.')).toBeInTheDocument()
    expect(calls.some((c) => c.url.endsWith('/prds/p1/finalise') && c.method === 'POST')).toBe(true)
    expect(screen.queryByRole('button', { name: 'Mark final' })).toBeNull()
  })

  it('final: shows the draft and the final note', async () => {
    mountWith([row('final', { prd: DOC })])
    expect(await screen.findByText('This PRD is final.')).toBeInTheDocument()
    expect(screen.getByText('A problem body.')).toBeInTheDocument()
  })

  it('Update draft requests a draft, then polls until it is a draft', async () => {
    mountWith([row('interviewing'), row('drafting'), row('draft', { prd: DOC })])
    await screen.findByText(/No draft yet/)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fireEvent.click(screen.getByRole('button', { name: 'Update draft' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/prds/p1/draft'))).toBe(true))
    await screen.findByRole('status')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100)
    })
    expect(await screen.findByText('A summary body.')).toBeInTheDocument()
    const before = calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000)
    })
    expect(calls.length).toBe(before) // polling stopped
  })

  it('failed with a previous draft: reason, previous draft and a retry', async () => {
    mountWith([row('failed', { prd: DOC, failure_reason: 'The draft failed to compile.' })])
    expect(await screen.findByText('The draft failed to compile.')).toBeInTheDocument()
    expect(screen.getByText('A summary body.')).toBeInTheDocument()
    expect(screen.getByText(/previous draft/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/prds/p1/draft'))).toBe(true))
  })

  it('failed without a previous draft: reason and retry, no draft', async () => {
    mountWith([row('failed', { failure_reason: 'Never started.' })])
    expect(await screen.findByText('Never started.')).toBeInTheDocument()
    expect(screen.queryByText('A summary body.')).toBeNull()
    expect(screen.queryByText(/previous draft/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled()
  })

  it('Download markdown fetches the .md route with the bearer token and saves it', async () => {
    const createObjectURL = vi.fn(() => 'blob:x')
    const revoke = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL: revoke }))
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    mountWith([row('draft', { prd: DOC })])
    fireEvent.click(await screen.findByRole('button', { name: 'Download markdown' }))
    await waitFor(() => expect(click).toHaveBeenCalled())
    const md = calls.find((c) => c.url === '/api/v1/plugins/idea-scout/candidates/c1/prd.md')
    expect(md?.auth).toBe('Bearer tok')
    expect(createObjectURL).toHaveBeenCalled()
    click.mockRestore()
  })
})
