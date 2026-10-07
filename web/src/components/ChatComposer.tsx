import { useLayoutEffect, useRef, type ReactNode } from 'react'

// Copied from biffo-plugin-ideation's ChatComposer. Class names are `prd-*`
// rather than `ide-*`: styles.test.ts forbids Ideation's prefix in this app's
// stylesheet.
export const COMPOSER_PLACEHOLDER =
  'Take your time — the more context you give, the better the result.'

const MIN_ROWS = 5

// Multi-line, auto-growing textarea. Enter inserts a newline; Ctrl+Enter /
// Cmd+Enter sends.
export function ChatComposer({
  label,
  value,
  onChange,
  onSend,
  busy,
  capped,
  children,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  onSend: () => void
  busy: boolean
  capped: boolean
  children?: ReactNode
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const disabled = busy || capped
  const canSend = !busy && !capped && value.trim().length > 0

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    const max = Math.max(160, Math.floor(window.innerHeight / 2))
    el.style.height = `${Math.min(el.scrollHeight, max)}px`
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
  }, [value])

  return (
    <div className="prd-compose">
      <textarea
        ref={ref}
        aria-label={label}
        value={value}
        rows={MIN_ROWS}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            if (canSend) onSend()
          }
        }}
        placeholder={COMPOSER_PLACEHOLDER}
        disabled={disabled}
      />
      <p className="prd-compose-hint">Enter for a new line · Ctrl+Enter (⌘+Enter on Mac) to send</p>
      <div className="prd-compose-actions">
        <button type="button" onClick={onSend} disabled={!canSend}>
          Send
        </button>
        {children}
      </div>
    </div>
  )
}
