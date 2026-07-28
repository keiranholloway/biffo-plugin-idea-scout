import type { Candidate, ScoreAxis, Scorecard } from '../lib/api'
import { pressureTestUrl } from '../lib/api'

// The four axes, in the order they are argued about. Labels are spelled out
// here rather than derived from the key so `economic_moat` does not surface as
// "Economic moat" in one place and "moat" in another.
const AXES: ReadonlyArray<{ key: keyof Scorecard; label: string; hint?: string }> = [
  { key: 'viability', label: 'Viability' },
  { key: 'complexity', label: 'Build complexity', hint: '5 = simple to build' },
  { key: 'economic_moat', label: 'Economic moat' },
  { key: 'market_fit', label: 'Market fit' },
]

/** Which band a score sits in, for the meter's colour.
 *
 * Bands, not a gradient, because these are judgements on a 1–5 scale and a
 * continuous ramp would imply a precision the model does not have. Note the
 * scale is magnitude, never goodness: `complexity` is inverted (5 = simple to
 * build), so a colour meaning "good" would be actively wrong on that axis.
 */
function band(score: number): string {
  if (score >= 4) return 'axis--high'
  if (score <= 2) return 'axis--low'
  return 'axis--mid'
}

function Axis({ label, hint, axis }: { label: string; hint?: string; axis: ScoreAxis }) {
  return (
    <div className={`axis ${band(axis.score)}`}>
      <div className="axis-head">
        <span className="axis-label">
          {label}
          {hint != null && <span className="axis-hint"> ({hint})</span>}
        </span>
        {/* The number is the claim; the rationale is the evidence. Both are
            shown, because a score with no reasoning is not reviewable. */}
        <span className="axis-score" aria-label={`${label}: ${axis.score} out of 5`}>
          {axis.score}/5
        </span>
      </div>
      {/* Decorative: the score is already announced by the head's aria-label,
          so the pips are hidden from assistive tech rather than repeating it. */}
      <div className="axis-meter" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((pip) => (
          <span key={pip} className={pip <= axis.score ? 'axis-pip axis-pip--on' : 'axis-pip'} />
        ))}
      </div>
      <p className="axis-rationale">{axis.rationale}</p>
    </div>
  )
}

export function CandidateCard({ candidate }: { candidate: Candidate }) {
  const { scorecard } = candidate
  return (
    <article className="candidate">
      <header className="candidate-head">
        <span className="candidate-rank" aria-label={`Ranked ${candidate.rank}`}>
          #{candidate.rank}
        </span>
        <h3 className="candidate-title">{candidate.title}</h3>
      </header>

      <p className="candidate-pitch">{candidate.pitch}</p>

      {scorecard != null && (
        <>
          <div className="scorecard">
            {AXES.map(({ key, label, hint }) => (
              <Axis key={key} label={label} hint={hint} axis={scorecard[key] as ScoreAxis} />
            ))}
          </div>

          <p className="candidate-summary">{scorecard.summary}</p>

          <p className="candidate-buildbuy">
            <strong>Build vs buy: </strong>
            {scorecard.build_vs_buy}
          </p>

          {scorecard.competitors.length > 0 && (
            <div className="candidate-competitors">
              <h4>Who else is here</h4>
              <ul>
                {scorecard.competitors.map((competitor) => (
                  <li key={competitor.name}>
                    {competitor.url != null && competitor.url !== '' ? (
                      <a href={competitor.url} target="_blank" rel="noreferrer">
                        {competitor.name}
                      </a>
                    ) : (
                      <span>{competitor.name}</span>
                    )}
                    {' — '}
                    {competitor.note}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {candidate.sources.length > 0 && (
        <details className="candidate-sources">
          {/* Collapsed by default: the evidence matters, but it is what you
              check *after* the idea interests you, not before. */}
          <summary>Evidence ({candidate.sources.length})</summary>
          <ul>
            {candidate.sources.map((source) => (
              <li key={source.url}>
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.url}
                </a>
                {' — '}
                {source.note}
              </li>
            ))}
          </ul>
        </details>
      )}

      <a className="candidate-promote" href={pressureTestUrl(candidate.pitch)}>
        Pressure-test this →
      </a>
    </article>
  )
}
