import { useEffect, useState } from "react";

import { nextDueLabel } from "../lib/cadence";
import type { Cadence } from "../lib/api";

/** The founder's own control over the automatic scout (#50).
 *
 * Three things have to be true of it, and they are the three the issue asked
 * for: a founder can SEE that cadence is on, CHANGE the interval, and turn it
 * OFF. The third is the one worth being careful about — turning it off here
 * writes `enabled: false`, and the *server* stops reporting the scout as due.
 * Nothing about this component's own rendering suppresses anything, which is
 * deliberate: a control that only hid itself would leave the auto-start firing
 * for a founder who had explicitly said no.
 *
 * The bounds on the interval come from the server in the same response as the
 * value. They are not restated here — the input's `min`/`max` must be the range
 * a save would actually accept, and this plugin has twice paid for a wording or
 * a range kept in two places.
 */
export function CadenceControl({
  cadence,
  busy,
  onSave,
}: {
  cadence: Cadence;
  busy: boolean;
  onSave: (enabled: boolean, cadenceDays: number) => void;
}) {
  // Local draft, so typing an interval does not fire a write per keystroke.
  // Re-seeded whenever the server's value changes (`useEffect` on the two
  // fields, not on the object — the object is a new reference on every fetch
  // and would clobber a half-typed value on any unrelated re-render).
  const [enabled, setEnabled] = useState(cadence.enabled);
  const [days, setDays] = useState(String(cadence.cadence_days));

  useEffect(() => {
    setEnabled(cadence.enabled);
    setDays(String(cadence.cadence_days));
  }, [cadence.enabled, cadence.cadence_days]);

  const parsed = Number.parseInt(days, 10);
  const valid =
    Number.isFinite(parsed) &&
    parsed >= cadence.min_cadence_days &&
    parsed <= cadence.max_cadence_days;
  const dirty = enabled !== cadence.enabled || parsed !== cadence.cadence_days;

  const due = nextDueLabel(cadence.next_due_at);

  return (
    <section className="cadence">
      <h2>Automatic scouting</h2>

      <label className="cadence-toggle">
        <input
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Scout for me automatically
      </label>

      <label className="cadence-interval">
        <span>Every</span>
        <input
          type="number"
          aria-label="Days between automatic scouts"
          value={days}
          min={cadence.min_cadence_days}
          max={cadence.max_cadence_days}
          // Left enabled while cadence is off: the interval is remembered
          // through the toggle, so a founder can set it up before switching on
          // rather than having to switch on, save, then set it.
          disabled={busy}
          onChange={(event) => setDays(event.target.value)}
        />
        <span>days</span>
      </label>

      {!valid && (
        <p className="cadence-invalid" role="status">
          Choose between {cadence.min_cadence_days} and {cadence.max_cadence_days} days.
        </p>
      )}

      {/* Says which of the two "nothing is due" cases this is, because the
          server sends `next_due_at: null` for both and only the surface knows
          which one reads as an explanation rather than a fault. */}
      <p className="cadence-status" role="status">
        {!cadence.enabled
          ? "Off — scouts only run when you press Run now."
          : due != null
            ? `Next scout ${due}.`
            : "Your first scout will be the one you start yourself."}
      </p>

      <button
        type="button"
        className="cadence-save"
        disabled={busy || !valid || !dirty}
        onClick={() => onSave(enabled, parsed)}
      >
        Save cadence
      </button>
    </section>
  );
}
