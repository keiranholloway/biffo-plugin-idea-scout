import { useEffect, useRef, useState } from 'react'

import type { Api, Candidate, PrdFull, PrdMessage, PrdState } from '../lib/api'
import { ChatComposer } from './ChatComposer'
import { PrdDraftPanel } from './PrdDraftPanel'

const PRD_POLL_MS = 3000

function describe(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

/** The PRD interview for one candidate.
 *
 * Opening POSTs `/candidates/{id}/prd`, which starts the interview or resumes
 * the existing one — either way the response carries the visible transcript.
 */
export function PrdView({
  api,
  candidate,
  onBack,
}: {
  api: Api
  candidate: Candidate
  onBack: () => void
}) {
  const [prd, setPrd] = useState<PrdState | null>(null)
  const [messages, setMessages] = useState<PrdMessage[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The stored row (draft, failure reason); null until the first read.
  const [full, setFull] = useState<PrdFull | null>(null)
  const [acting, setActing] = useState(false)
  const prdId = prd?.id
  const status = full?.status ?? prd?.status
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setBusy(true)
    api
      .startPrd(candidate.id)
      .then(({ messages: transcript, ...state }) => {
        if (cancelled) return
        setPrd(state)
        setMessages(transcript)
        return api.getPrd(state.id).then((row) => {
          if (!cancelled) setFull(row)
        })
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describe(err))
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [api, candidate.id])

  // Poll the stored PRD while it is drafting (reading is what settles it),
  // stopping once it is draft or failed.
  useEffect(() => {
    if (prdId == null || status !== 'drafting') return
    const timer = setInterval(() => {
      void api
        .getPrd(prdId)
        .then((row) => {
          if (mounted.current) setFull(row)
        })
        .catch((err: unknown) => {
          if (mounted.current) setError(describe(err))
        })
    }, PRD_POLL_MS)
    return () => clearInterval(timer)
  }, [api, prdId, status])

  async function act(fn: () => Promise<PrdFull>) {
    setActing(true)
    setError(null)
    try {
      setFull(await fn())
    } catch (err: unknown) {
      setError(describe(err))
    } finally {
      setActing(false)
    }
  }

  async function download() {
    setError(null)
    try {
      const { blob, filename } = await api.downloadPrdMarkdown(candidate.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      setError(describe(err))
    }
  }

  async function send() {
    const text = draft.trim()
    if (prd == null || text === '') return
    setBusy(true)
    setError(null)
    try {
      const { reply, ...state } = await api.sendPrdMessage(prd.id, text)
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: text },
        { role: 'assistant', content: reply },
      ])
      setPrd(state)
      setFull((prev) => (prev == null ? prev : { ...prev, status: state.status }))
      setDraft('')
    } catch (err: unknown) {
      setError(describe(err))
    } finally {
      setBusy(false)
    }
  }

  const drafting = status === 'drafting'
  const atCap = prd != null && prd.turn_count >= prd.max_turns

  return (
    <section className="prd-view">
      <button type="button" className="prd-back" onClick={onBack}>
        ← Back to candidates
      </button>
      <h2 className="prd-title">{candidate.title}</h2>
      {error != null && <p className="error">{error}</p>}
      {prd == null && busy && <p className="muted">Opening the PRD interview…</p>}

      {prd != null && (
        <>
          <p className="prd-turns">
            Turn {prd.turn_count} of {prd.max_turns}
          </p>
          <ul className="prd-messages" aria-label="PRD transcript">
            {messages.map((m, i) => (
              <li key={i} className={`prd-msg prd-msg--${m.role}`}>
                <span className="prd-who">{m.role === 'user' ? 'You' : 'PRD agent'}</span>
                <p>{m.content}</p>
              </li>
            ))}
          </ul>
          {drafting && (
            <p className="in-flight" role="status">
              Drafting the PRD — the chat is paused until it finishes.
            </p>
          )}
          {atCap && !drafting && (
            <p className="prd-cap" role="status">
              Turn limit reached ({prd.max_turns} of {prd.max_turns}). The interview is complete.
            </p>
          )}
          <div className="prd-draft-panel">
            <h3 className="prd-draft-title">Draft</h3>
            <div className="prd-draft-actions">
              <button
                type="button"
                onClick={() => void act(() => api.draftPrd(prd.id))}
                disabled={acting || drafting}
              >
                {status === 'failed' ? 'Retry' : 'Update draft'}
              </button>
              {status === 'draft' && (
                <button
                  type="button"
                  onClick={() => void act(() => api.finalisePrd(prd.id))}
                  disabled={acting}
                >
                  Mark final
                </button>
              )}
              {full?.prd != null && (
                <button type="button" onClick={() => void download()}>
                  Download markdown
                </button>
              )}
            </div>
            {status === 'final' && (
              <p className="prd-final" role="status">
                This PRD is final.
              </p>
            )}
            {status === 'failed' && (
              <p className="error" role="alert">
                {full?.failure_reason ?? 'The draft failed.'}
              </p>
            )}
            {status === 'failed' && full?.prd != null && (
              <p className="muted">Showing your previous draft.</p>
            )}
            {full?.prd != null ? (
              <PrdDraftPanel prd={full.prd} />
            ) : (
              status !== 'drafting' && <p className="muted">No draft yet. Keep talking, then press Update draft.</p>
            )}
          </div>
          <ChatComposer
            label="Your reply"
            value={draft}
            onChange={setDraft}
            onSend={() => void send()}
            busy={busy}
            capped={drafting || atCap}
          />
        </>
      )}
    </section>
  )
}
