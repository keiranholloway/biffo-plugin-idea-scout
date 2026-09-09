/**
 * The pull-based auto-scout cadence (#50, option A).
 *
 * A founder should not have to remember to come back and press "Run now"
 * themselves. Rather than a scheduler that fires while nobody is looking
 * (rejected — it spends money on founders who never open the page), the
 * surface checks staleness only when a founder actually returns to it: if
 * their most recent scout is older than the cadence, App.tsx starts a fresh
 * one on their behalf instead of showing the empty form.
 *
 * `idea_scout_runs.created_at` already exists per owner, so "how long since
 * their last run" is derived from data that is already there — no new table,
 * no new column (estate fix-ladder level 2: derive what would otherwise be
 * maintained by hand).
 *
 * `DEFAULT_CADENCE_DAYS` is a single constant rather than an owner-scoped
 * preference: this plugin has no owner-scoped settings store to hang a
 * preference on yet, and adding one was explicitly out of scope for this
 * change. Making the interval founder-configurable is named as remaining
 * work on issue #50.
 */
export const DEFAULT_CADENCE_DAYS = 7

const MS_PER_DAY = 24 * 60 * 60 * 1000

/**
 * Whether a run is old enough that a founder returning to the page should get
 * a fresh one automatically, rather than the one they last read.
 *
 * A missing or unparseable timestamp counts as stale rather than fresh: Core
 * always sets `created_at`, so this only fires on a malformed value, and
 * treating that as "we don't know, so act as if it's old" costs at most one
 * extra run — the safe side, unlike treating it as fresh and never offering a
 * founder a new scout again.
 */
export function isStale(
  createdAt: string | null,
  now: Date = new Date(),
  cadenceDays: number = DEFAULT_CADENCE_DAYS,
): boolean {
  const created = createdAt == null ? null : new Date(createdAt)
  if (created == null || Number.isNaN(created.getTime())) return true
  return now.getTime() - created.getTime() >= cadenceDays * MS_PER_DAY
}

/**
 * Whole days since `createdAt`, for the "started automatically" explanation.
 * `null` when there is nothing trustworthy to show, the same convention
 * `startedAt` uses — rendering a wrong number is worse than omitting it.
 */
export function ageInDays(createdAt: string | null, now: Date = new Date()): number | null {
  if (createdAt == null) return null
  const created = new Date(createdAt)
  if (Number.isNaN(created.getTime())) return null
  return Math.floor((now.getTime() - created.getTime()) / MS_PER_DAY)
}
