/**
 * When a scout was kicked off, formatted for the Past scouts list.
 *
 * A scout takes minutes and a founder may come back to it hours or days later,
 * so "which of these is the one I started this morning?" is a real question the
 * sidebar could not answer — every entry showed only its build type and status,
 * and a founder who has run MicroSaaS three times saw three identical rows.
 *
 * Timezone: Core emits `created_at` as ISO 8601 **with** an explicit `Z`
 * (verified against the deployed API: `2026-07-28T12:55:23.240947Z`), so
 * `new Date()` parses it as UTC and `toLocaleString` renders the founder's own
 * local time. Do **not** append a `Z` defensively — on an already-marked string
 * that produces an invalid date, which is worse than the bug it guards against.
 */

export interface StartedAt {
  /** Short local form for the list, e.g. "28 Jul, 13:55". */
  readonly label: string;
  /** The original ISO string, for a `<time dateTime>` attribute. */
  readonly iso: string;
  /** Full local form for a tooltip, e.g. "28 July 2026 at 13:55:23". */
  readonly title: string;
}

/**
 * Returns null when there is nothing trustworthy to show — a missing value, or
 * one that does not parse. Rendering "Invalid Date" to a founder is worse than
 * rendering nothing, and `created_at` is typed nullable because Core may omit
 * it, not because it is normally absent.
 */
export function startedAt(iso: string | null | undefined): StartedAt | null {
  if (iso == null || iso === "") return null;

  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;

  return {
    iso,
    label: date.toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }),
    title: date.toLocaleString(undefined, {
      dateStyle: "long",
      timeStyle: "medium",
    }),
  };
}
