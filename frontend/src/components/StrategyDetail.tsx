import type { Statement, Strategy } from '../api/client'
import { dayLabel, num } from '../format'
import { useLang, useT, type MessageKey } from '../i18n'

function Statements({ items }: { items: Statement[] }) {
  return (
    <ul className="statements">
      {items.map((s, i) => (
        <li key={`${s.code}-${i}`} data-code={s.code} className={s.code.startsWith('tradeoff.') ? 'tradeoff' : ''}>
          {s.text}
        </li>
      ))}
    </ul>
  )
}

/** The five explanation elements of one strategy, plus its calendar as a table. */
export default function StrategyDetail({ strategy }: { strategy: Strategy }) {
  const t = useT()
  const lang = useLang()

  return (
    <section className="panel detail" aria-labelledby="detail-title" data-detail={strategy.id}>
      <h2 id="detail-title">
        {strategy.label}
        <span className="muted detail-sequence"> &middot; {strategy.slots.filter((s) => s.role === 'main').map((s) => s.crop_name).join(' → ')}</span>
      </h2>

      <div className="detail-grid">
        <div data-element="why">
          <h3>{t('detail.why')}</h3>
          <Statements items={strategy.why} />
        </div>
        <div data-element="benefits">
          <h3>{t('detail.benefits')}</h3>
          <Statements items={strategy.benefits} />
        </div>
        <div data-element="gaps">
          <h3>{t('detail.gaps')}</h3>
          <Statements items={strategy.gaps} />
        </div>
        <div data-element="local_review">
          <h3>{t('detail.review')}</h3>
          <Statements items={strategy.local_review} />
        </div>
      </div>

      <div data-element="evidence">
        <h3>{t('detail.evidence')}</h3>
        <div className="table-scroll">
          <table className="evidence">
            <thead>
              <tr>
                <th>{t('evidence.indicator')}</th>
                <th className="num">{t('evidence.value')}</th>
                <th>{t('evidence.source')}</th>
                <th>{t('evidence.period')}</th>
                <th>{t('evidence.resolution')}</th>
                <th>{t('evidence.scope')}</th>
              </tr>
            </thead>
            <tbody>
              {strategy.evidence.map((e) => (
                <tr key={e.indicator} title={`${t('evidence.method')}: ${e.method}`}>
                  <td>
                    {e.label}
                    <div className="muted method">{e.method}</div>
                  </td>
                  <td className="num nowrap">
                    {num(e.value, Number.isInteger(e.value) ? 0 : Math.abs(e.value) < 10 ? 2 : 1, lang)} <span className="muted">{e.unit}</span>
                  </td>
                  <td>{e.source}</td>
                  <td className="nowrap">{e.period}</td>
                  <td>{e.resolution}</td>
                  <td>{t(`scope.${e.scope}` as MessageKey)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <details className="calendar-table">
        <summary>{t('detail.calendar')}</summary>
        <table className="evidence">
          <tbody>
            {strategy.slots.map((slot, i) => (
              <tr key={i}>
                <td>
                  {slot.crop_name}
                  {slot.role === 'cover' && <span className="muted"> ({t('detail.cover')})</span>}
                </td>
                <td>
                  {t('detail.sow')}: {dayLabel(slot.sow.doy, lang)}, {t('strategies.year').toLowerCase()} {slot.sow.year_index + 1}
                </td>
                <td>
                  {t('detail.harvest')}: {dayLabel(slot.harvest.doy, lang)}, {t('strategies.year').toLowerCase()} {slot.harvest.year_index + 1}
                </td>
                <td className="num">
                  {slot.days} {t('site.bare.days')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}
