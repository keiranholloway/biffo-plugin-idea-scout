/**
 * Presentation helpers for the pull-based auto-scout cadence (#50, option A).
 *
 * A founder should not have to remember to come back and press "Run now"
 * themselves. Rather than a scheduler that fires while nobody is looking
 * (rejected — it spends money on founders who never open the page), the
 * surface checks staleness only when a founder actually returns to it.
 *
 * **The staleness decision is not here, and must not come back here.** It lives
 * on the server, in `service._derive_cadence_state`, and arrives as
 * `Cadence.is_due`. This module used to own an `isStale` that compared
 * `created_at` against a hardcoded `DEFAULT_CADENCE_DAYS = 7`; once the
 * interval became an owner-scoped preference, a second copy of that rule — in
 * a second language, against a constant that no longer matched what the
 * founder had chosen — could only ever have gone wrong. What is left here is
 * copy: turning timestamps into words.
 *
 * Both functions return `null` rather than a guess when there is nothing
 * trustworthy to show, the same convention `startedAt` uses. Rendering a wrong
 * number is worse than omitting it.
 */

const MS_PER_DAY = 24 * 60 * 60 * 1000

/**
 * Whole days since `createdAt`, for the "started automatically" explanation.
 */
export function ageInDays(createdAt: string | null, now: Date = new Date()): number | null {
  if (createdAt == null) return null
  const created = new Date(createdAt)
  if (Number.isNaN(created.getTime())) return null
  return Math.floor((now.getTime() - created.getTime()) / MS_PER_DAY)
}

/**
 * When the next automatic scout falls due, in words.
 *
 * `nextDueAt` is the server's derived value — this only phrases it. `null` in
 * gives `null` out, which is the "cadence is off, or there is no run to measure
 * from" case; the component says which of those it is, because only it knows.
 *
 * Rounds *up* to whole days ("in 1 day" until the moment it is due, never a
 * silent "in 0 days"), so the label never claims a scout is further off than
 * the next page load.
 */
export function nextDueLabel(nextDueAt: string | null, now: Date = new Date()): string | null {
  if (nextDueAt == null) return null
  const due = new Date(nextDueAt)
  if (Number.isNaN(due.getTime())) return null

  const remaining = due.getTime() - now.getTime()
  if (remaining <= 0) return 'due now'

  const days = Math.ceil(remaining / MS_PER_DAY)
  return days === 1 ? 'due tomorrow' : `due in ${days} days`
}
