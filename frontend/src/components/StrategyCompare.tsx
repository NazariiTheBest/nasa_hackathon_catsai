import type { Strategy } from '../api/client'
import { num, signed, OBJECTIVES, type CropGroup } from '../format'
import { useLang, useT } from '../i18n'
import CalendarStrip, { useTip } from './CalendarStrip'

interface Props {
  strategies: Strategy[]
  selectedId: string | null
  onSelect: (id: string) => void
  groupOf: (cropId: string) => CropGroup
}

const CONFIDENCE_STEPS = { low: 1, medium: 2, high: 3 } as const

/** Baseline and alternatives side by side: sequence, score with its interval, confidence, goals. */
export default function StrategyCompare({ strategies, selectedId, onSelect, groupOf }: Props) {
  const t = useT()
  const lang = useLang()
  const { bind, node } = useTip()
  const baseline = strategies.find((s) => s.is_baseline)

  return (
    <section className="panel" aria-labelledby="strategies-title">
      <h2 id="strategies-title">{t('strategies.title')}</h2>
      <div className="legend">
        {(['cereal', 'broadleaf', 'legume'] as const).map((group) => (
          <span key={group} className="key">
            <span className={`swatch seg-${group}`} />
            {t(`legend.${group}`)}
          </span>
        ))}
        <span className="key">
          <span className="swatch swatch-cover seg-cereal" />
          {t('legend.cover')}
        </span>
        <span className="key">
          <span className="swatch swatch-bare" />
          {t('legend.bare')}
        </span>
      </div>

      <div className="cards">
        {strategies.map((s) => {
          const overall = s.scores.overall
          const selected = s.id === selectedId
          return (
            <article key={s.id} className={`card${selected ? ' card-selected' : ''}`} data-strategy={s.id} data-baseline={s.is_baseline}>
              <header className="card-head">
                <h3>{s.label}</h3>
                {s.is_baseline && <span className="tag tag-strong">{t('strategies.baseline')}</span>}
                <span className="muted">
                  {s.cycle_years} {t('strategies.years')}
                </span>
              </header>

              <ol className="sequence">
                {s.slots.map((slot, i) => (
                  <li key={i} className={slot.role === 'cover' ? 'sequence-cover' : ''}>
                    <span className={`swatch seg-${groupOf(slot.crop_id)}${slot.role === 'cover' ? ' swatch-cover' : ''}`} />
                    {slot.crop_name}
                  </li>
                ))}
              </ol>
              <CalendarStrip slots={s.slots} cycleYears={s.cycle_years} groupOf={groupOf} />

              <div className="score">
                <div className="score-label">{t('strategies.overall')}</div>
                <div className="score-line">
                  <span className="score-value">{num(overall.median, 2, lang)}</span>
                  <span
                    className="range" tabIndex={0}
                    {...bind(
                      <>
                        <strong>{t('strategies.overall')}</strong>: {num(overall.median, 2, lang)}
                        <br />
                        {num(overall.p10, 2, lang)} &ndash; {num(overall.p90, 2, lang)} ({t('strategies.range')} {overall.windows}{' '}
                        {t('strategies.windows')})
                      </>,
                    )}
                  >
                    <span className="range-band" style={{ left: `${overall.p10 * 100}%`, width: `${Math.max((overall.p90 - overall.p10) * 100, 1)}%` }} />
                    <span className="range-dot" style={{ left: `${overall.median * 100}%` }} />
                  </span>
                </div>
                <div className="muted score-interval">
                  {num(overall.p10, 2, lang)} &ndash; {num(overall.p90, 2, lang)} &middot; {t('strategies.range')} {overall.windows} {t('strategies.windows')}
                </div>
              </div>

              <div className="confidence" data-confidence={s.confidence}>
                <span>{t('strategies.confidence')}:</span>
                <span className="steps" aria-hidden="true">
                  {[1, 2, 3].map((step) => (
                    <span key={step} className={step <= CONFIDENCE_STEPS[s.confidence] ? 'step on' : 'step'} />
                  ))}
                </span>
                <strong>{t(`confidence.${s.confidence}`)}</strong>
              </div>

              <h4>{t('strategies.objectives')}</h4>
              <ul className="objectives">
                {OBJECTIVES.map((name) => {
                  const value = s.scores.objectives[name] ?? 0
                  const base = baseline?.scores.objectives[name] ?? value
                  const delta = s.vs_baseline?.objectives[name] ?? 0
                  const direction = delta > 0.005 ? 'up' : delta < -0.005 ? 'down' : 'flat'
                  return (
                    <li key={name} className="objective" data-objective={name}>
                      <span className="objective-label">{t(`objective.${name}`)}</span>
                      <span
                        className="bar" tabIndex={0}
                        {...bind(
                          <>
                            <strong>{t(`objective.${name}`)}</strong>: {num(value, 2, lang)}
                            {!s.is_baseline && (
                              <>
                                <br />
                                {t('strategies.baselineMark')}: {num(base, 2, lang)} ({signed(delta, 2, lang)})
                              </>
                            )}
                          </>,
                        )}
                      >
                        <span className="bar-fill" style={{ width: `${value * 100}%` }} />
                        {!s.is_baseline && <span className="bar-mark" style={{ left: `${base * 100}%` }} />}
                      </span>
                      <span className="figure">{num(value, 2, lang)}</span>
                      <span className={`delta delta-${direction}`}>
                        {!s.is_baseline && direction !== 'flat' && (
                          <>
                            <span aria-hidden="true">{direction === 'up' ? '▲' : '▼'}</span> {signed(delta, 2, lang)}
                          </>
                        )}
                      </span>
                    </li>
                  )
                })}
              </ul>
              {!s.is_baseline && (
                <p className="muted mark-note">
                  <span className="bar-mark-key" /> {t('strategies.baselineMark')}
                </p>
              )}

              <footer className="card-foot">
                <span className="muted">
                  {s.gaps.length} {t('strategies.gaps')} &middot; {s.local_review.length} {t('strategies.reviews')}
                </span>
                <button type="button" className="secondary" aria-pressed={selected} onClick={() => onSelect(s.id)}>
                  {selected ? t('strategies.selected') : t('strategies.details')}
                </button>
              </footer>
            </article>
          )
        })}
      </div>
      {node}
    </section>
  )
}
