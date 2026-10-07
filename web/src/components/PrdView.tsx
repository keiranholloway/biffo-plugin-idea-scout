import { useEffect, useState } from 'react'

import type { Api, Candidate, PrdMessage, PrdState } from '../lib/api'
import { ChatComposer } from './ChatComposer'

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

  useEffect(() => {
    let cancelled = false
    setBusy(true)
    api
      .startPrd(candidate.id)
      .then(({ messages: transcript, ...state }) => {
        if (cancelled) return
        setPrd(state)
        setMessages(transcript)
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
      setDraft('')
    } catch (err: unknown) {
      setError(describe(err))
    } finally {
      setBusy(false)
    }
  }

  const drafting = prd?.status === 'drafting'
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
