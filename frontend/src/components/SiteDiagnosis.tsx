import type { Site, Slot } from '../api/client'
import { dayLabel, num, signed, type CropGroup } from '../format'
import { useLang, useT } from '../i18n'
import CalendarStrip, { useTip } from './CalendarStrip'

interface Props {
  site: Site
  baselineSlots: Slot[]
  cycleYears: number
  groupOf: (cropId: string) => CropGroup
}

/** Site diagnosis: bare-soil windows, crop stress, water balance and long-term trends. */
export default function SiteDiagnosis({ site, baselineSlots, cycleYears, groupOf }: Props) {
  const t = useT()
  const lang = useLang()
  const { bind, node } = useTip()
  const maxDemand = Math.max(1, ...site.water_balance.map((w) => w.demand_mm))

  return (
    <section className="panel" aria-labelledby="site-title">
      <h2 id="site-title">{t('site.title')}</h2>

      <div className="diag-grid">
        <div className="diag-block" data-block="bare">
          <h3>{t('site.bare')}</h3>
          <CalendarStrip slots={baselineSlots} cycleYears={cycleYears} groupOf={groupOf} />
          <ul className="rows">
            {site.bare_windows.map((w, i) => (
              <li key={i} className="row">
                <div className="row-head">
                  <span>
                    {dayLabel(w.start.doy, lang)} &rarr; {dayLabel(w.end.doy, lang)}
                    <span className="muted"> &middot; {t('site.bare.after')} {w.after_crop_name}</span>
                  </span>
                  <strong className="figure">
                    {w.days} {t('site.bare.days')}
                  </strong>
                </div>
                <div className="meter-line">
                  <span className="meter-label">{t('site.bare.exposure')}</span>
                  <span
                    className="meter" tabIndex={0}
                    {...bind(
                      <>
                        {t('site.bare.exposure')}: <strong>{num(w.erosion_exposure, 2, lang)}</strong> (0-1)
                        <br />
                        {num(w.erosive_rain_mm, 0, lang)} {t('site.bare.rain')}
                        {w.rain_only && (
                          <>
                            <br />
                            {t('site.bare.rainOnly')}
                          </>
                        )}
                      </>,
                    )}
                  >
                    <span className="meter-fill" style={{ width: `${w.erosion_exposure * 100}%` }} />
                  </span>
                  <span className="figure">{num(w.erosion_exposure, 2, lang)}</span>
                </div>
              </li>
            ))}
          </ul>
          {site.observed_low_cover.length > 0 && (
            <p className="note">
              <strong>{t('site.lowCover')}:</strong>{' '}
              {site.observed_low_cover.map((p, i) => (
                <span key={i}>
                  {i > 0 && '; '}
                  {dayLabel(p.start_doy, lang)} &rarr; {dayLabel(p.end_doy, lang)}, NDVI {num(p.median_ndvi, 2, lang)} ({p.source}, {p.resolution},{' '}
                  {p.years} {t('site.lowCover.years')})
                </span>
              ))}
            </p>
          )}
        </div>

        <div className="diag-block" data-block="stress">
          <h3>{t('site.stress')}</h3>
          <table className="stress-table">
            <tbody>
              {site.stress.map((s, i) => (
                <tr key={i}>
                  <th scope="row">
                    {s.crop_name}
                    <span className="muted"> &middot; {s.hazard_label}</span>
                  </th>
                  <td className="stress-bar-cell">
                    <span
                      className="meter" tabIndex={0}
                      {...bind(
                        <>
                          <strong>
                            {s.crop_name}: {s.hazard_label}
                          </strong>
                          <br />
                          {s.stage_label}, {dayLabel(s.window_start_doy, lang)} &rarr; {dayLabel(s.window_end_doy, lang)}
                          <br />
                          {s.years_hit} {t('site.stress.of')} {s.years_total} {t('site.stress.years')}
                        </>,
                      )}
                    >
                      <span className="meter-fill" style={{ width: `${s.probability * 100}%` }} />
                    </span>
                  </td>
                  <td className="figure">{num(s.probability * 100, 0, lang)}%</td>
                  <td className="muted nowrap">
                    {s.years_hit} {t('site.stress.of')} {s.years_total}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="diag-block" data-block="water">
          <h3>{t('site.water')}</h3>
          <div className="legend">
            <span className="key">
              <span className="swatch swatch-supply" />
              {t('site.water.supply')}
            </span>
            <span className="key">
              <span className="swatch swatch-deficit" />
              {t('site.water.deficit')}
            </span>
          </div>
          <ul className="rows">
            {site.water_balance.map((w, i) => (
              <li key={i} className="row">
                <div className="row-head">
                  <span>{w.crop_name}</span>
                  <span className="figure">
                    {num(w.supply_mm, 0, lang)} + {num(w.deficit_mm, 0, lang)} = {num(w.demand_mm, 0, lang)} mm
                  </span>
                </div>
                <span
                  className="split" tabIndex={0} style={{ width: `${(w.demand_mm / maxDemand) * 100}%` }}
                  {...bind(
                    <>
                      <strong>{w.crop_name}</strong>
                      <br />
                      {t('site.water.supply')}: {num(w.supply_mm, 0, lang)} mm
                      <br />
                      {t('site.water.deficit')}: {num(w.deficit_mm, 0, lang)} mm
                    </>,
                  )}
                >
                  <span className="split-supply" style={{ flexGrow: Math.max(w.supply_mm, 0.001) }} />
                  {w.deficit_mm > 0 && <span className="split-deficit" style={{ flexGrow: w.deficit_mm }} />}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="diag-block" data-block="trends">
          <h3>{t('site.trends')}</h3>
          <ul className="rows">
            {site.trends.map((tr) => (
              <li key={tr.indicator} className={`row trend${tr.significant ? '' : ' trend-ns'}`} data-significant={tr.significant}>
                <div className="row-head">
                  <span>{tr.label}</span>
                  <span className={`tag ${tr.significant ? 'tag-strong' : 'tag-muted'}`}>
                    {tr.significant ? t('site.trends.significant') : t('site.trends.notSignificant')}
                  </span>
                </div>
                <div className="trend-value">
                  <strong className="figure">
                    {signed(tr.slope_per_decade, Math.abs(tr.slope_per_decade) < 10 ? 2 : 0, lang)} {tr.unit}
                  </strong>{' '}
                  <span className="muted">
                    {t('site.trends.perDecade')} &middot; {tr.period} &middot; p = {num(tr.p_value, 3, lang)} &middot; {tr.source}
                  </span>
                </div>
              </li>
            ))}
          </ul>
          {site.anomalies.length > 0 && (
            <>
              <h4>{t('site.anomalies')}</h4>
              <ul className="rows">
                {site.anomalies.map((a) => (
                  <li key={a.variable} className="row">
                    <div className="row-head">
                      <span>{a.label}</span>
                      <span className="muted">
                        {a.source} &middot; {a.period}
                      </span>
                    </div>
                    <div className="muted">
                      {a.recent.map((r) => `${r.year}: ${signed(r.anomaly, 3, lang)}`).join(' · ')} {a.unit} {t('site.anomalies.vsMean')}{' '}
                      {a.n_years} {t('site.lowCover.years')} ({num(a.mean, 3, lang)})
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      <div className="sources">
        <h3>{t('site.sources')}</h3>
        <p>
          <strong>{t('site.climate')}:</strong> {site.climate.source}, {site.climate.spatial_resolution}, {site.climate.period} ({site.climate.years}{' '}
          {t('site.lowCover.years')})
        </p>
        <p>
          <strong>{t('site.soil')}:</strong> {num(site.soil.awc_mm_per_m, 0, lang)} mm/m ({t(`site.soil.${site.soil.awc_status}`)}
          {site.soil.source ? `, ${site.soil.source}` : ''})
        </p>
        {site.information_gaps.length > 0 && (
          <>
            <p>
              <strong>{t('site.gaps')}:</strong>
            </p>
            <ul className="plain">
              {site.information_gaps.map((g) => (
                <li key={g.code}>{g.text}</li>
              ))}
            </ul>
          </>
        )}
      </div>
      {node}
    </section>
  )
}
