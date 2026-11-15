import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  ApiError,
  type AnalyzeRequest,
  type AnalyzeResponse,
  type Constraints,
  type CropEntry,
  type Lang,
  type LocateResponse,
  type Priorities,
  type ShowcaseCollection,
} from './api/client'
import MapPanel, { type PickedLocation } from './components/MapPanel'
import PrioritiesForm from './components/PrioritiesForm'
import RotationBuilder, { type RotationEntry } from './components/RotationBuilder'
import SiteDiagnosis from './components/SiteDiagnosis'
import StrategyCompare from './components/StrategyCompare'
import StrategyDetail from './components/StrategyDetail'
import { cropGroup } from './format'
import { LangContext, useT } from './i18n'

const DEFAULT_PRIORITIES: Priorities = { water: 0.8, nitrogen: 0.4, erosion: 0.6, organic_matter: 0.5, forage: 0, income: 0.7 }
const DEFAULT_CONSTRAINTS: Required<Constraints> = { irrigation_available: false, excluded_crops: [], max_cycle_years: 5 }
const DEFAULT_ROTATION: RotationEntry[] = [
  { crop: 'winter_wheat', cover: null },
  { crop: 'sunflower', cover: null },
]

/**
 * Run a start-up request, trying again every few seconds while it fails, so a page opened
 * before the backend is ready fills in by itself. Returns a cleanup that stops the retries.
 */
function retrying(load: () => Promise<unknown>, everyMs = 3000, attempts = 20): () => void {
  let active = true
  let timer: number | undefined
  const attempt = (left: number) => {
    load().catch(() => {
      if (active && left > 1) timer = window.setTimeout(() => attempt(left - 1), everyMs)
    })
  }
  attempt(attempts)
  return () => {
    active = false
    window.clearTimeout(timer)
  }
}

function initialLang(): Lang {
  try {
    return localStorage.getItem('fieldshift.lang') === 'uk' ? 'uk' : 'en'
  } catch {
    return 'en'
  }
}

export default function App() {
  const [lang, setLang] = useState<Lang>(initialLang)
  return (
    <LangContext.Provider value={lang}>
      <Workspace lang={lang} onLang={setLang} />
    </LangContext.Provider>
  )
}

function Workspace({ lang, onLang }: { lang: Lang; onLang: (lang: Lang) => void }) {
  const t = useT()
  const [crops, setCrops] = useState<CropEntry[]>([])
  const [showcase, setShowcase] = useState<ShowcaseCollection | null>(null)
  const [location, setLocation] = useState<PickedLocation | null>(null)
  const [located, setLocated] = useState<LocateResponse | null>(null)
  const [rotation, setRotation] = useState<RotationEntry[]>(DEFAULT_ROTATION)
  const [priorities, setPriorities] = useState<Priorities>(DEFAULT_PRIORITIES)
  const [constraints, setConstraints] = useState<Required<Constraints>>(DEFAULT_CONSTRAINTS)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [result, setResult] = useState<AnalyzeResponse | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const lastRequest = useRef<AnalyzeRequest | null>(null)
  const sequence = useRef(0)
  const inFlight = useRef(false)

  useEffect(() => {
    document.documentElement.lang = lang
    try {
      localStorage.setItem('fieldshift.lang', lang)
    } catch {
      /* storage may be unavailable; the choice then lasts for this visit only */
    }
    return retrying(() => api.crops(lang).then((catalog) => setCrops(catalog.crops)))
  }, [lang])

  useEffect(() => retrying(() => api.showcase().then(setShowcase)), [])

  useEffect(() => {
    if (!location) return
    let current = true
    setLocated(null)
    api
      .locate(location.lat, location.lon)
      .then((response) => current && setLocated(response))
      .catch(() => current && setLocated(null))
    return () => {
      current = false
    }
  }, [location])

  const run = useCallback(async (request: AnalyzeRequest, keepPrevious: boolean) => {
    if (inFlight.current) return // one analysis at a time
    inFlight.current = true
    const ticket = ++sequence.current
    setRunning(true)
    setError(null)
    if (!keepPrevious) setResult(null) // never show an earlier result as the outcome of this run
    lastRequest.current = request
    try {
      const response = await api.analyze(request)
      if (ticket !== sequence.current) return
      setResult(response)
      // The climate series is stored after a first analysis; refresh the location status to say so.
      api.locate(response.site.lat, response.site.lon).then(setLocated).catch(() => undefined)
      setSelectedId((previous) =>
        response.strategies.some((s) => s.id === previous) ? previous : (response.strategies.find((s) => !s.is_baseline)?.id ?? response.strategies[0]?.id ?? null),
      )
    } catch (caught) {
      if (ticket !== sequence.current) return
      setResult(null)
      setError(caught instanceof ApiError ? caught : new ApiError(0, 'server_error', String(caught)))
    } finally {
      inFlight.current = false
      if (ticket === sequence.current) setRunning(false)
    }
  }, [])

  function buildRequest(): AnalyzeRequest | null {
    if (!location || rotation.length === 0) return null
    return {
      location:
        location.kind === 'unit' && location.unitId
          ? { type: 'unit', unit_id: location.unitId }
          : { type: 'point', lat: location.lat, lon: location.lon },
      baseline: {
        crops: rotation.map((entry) => entry.crop),
        covers: rotation.flatMap((entry, index) => (entry.cover ? [{ after_index: index, crop_id: entry.cover }] : [])),
      },
      priorities,
      constraints,
      lang,
    }
  }

  // Analysis text is produced by the API in one language, so a language switch re-requests it.
  // It waits for a run in progress to finish, so results never stay in the previous language.
  useEffect(() => {
    const previous = lastRequest.current
    if (!running && previous && previous.lang !== lang && (result || error)) {
      void run({ ...previous, lang }, true)
    }
  }, [lang, running]) // eslint-disable-line react-hooks/exhaustive-deps

  const groupOf = useMemo(() => {
    const byId = new Map(crops.map((c) => [c.id, c]))
    return (cropId: string) => cropGroup(byId.get(cropId))
  }, [crops])

  const request = buildRequest()
  const blocked = !location ? t('run.needLocation') : rotation.length === 0 ? t('rotation.empty') : null
  const baseline = result?.strategies.find((s) => s.is_baseline)
  const selected = result?.strategies.find((s) => s.id === selectedId)

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>{t('app.title')}</h1>
          <p className="tagline">{t('app.tagline')}</p>
        </div>
        <div className="lang-switch" role="group" aria-label={t('lang.label')}>
          {(['en', 'uk'] as const).map((code) => (
            <button key={code} type="button" className={code === lang ? 'on' : ''} aria-pressed={code === lang} data-lang={code} onClick={() => onLang(code)}>
              {code === 'en' ? 'EN' : 'УКР'}
            </button>
          ))}
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <section className="panel" data-step="location">
            <h2>{t('location.title')}</h2>
            <p className="hint">{t('location.hint')}</p>
            {!location && <p className="muted">{t('location.none')}</p>}
            {location && (
              <div className="location-status" data-tier={located?.data_tier ?? ''}>
                <div>
                  <strong>{location.kind === 'unit' ? `${t('location.field')}: ${location.name ?? location.unitId}` : t('location.point')}</strong>
                  <span className="muted"> {location.lat.toFixed(4)}, {location.lon.toFixed(4)}</span>
                </div>
                {located && (
                  <>
                    <div className={`tier tier-${located.data_tier}`}>
                      <span className="tier-steps" aria-hidden="true">
                        {[1, 2, 3].map((step) => (
                          <span key={step} className={step <= { climate_only: 1, grid: 2, field: 3 }[located.data_tier] ? 'step on' : 'step'} />
                        ))}
                      </span>
                      <strong>{t(`tier.${located.data_tier}`)}</strong>
                    </div>
                    <p className="hint">{t(`tier.${located.data_tier}.note`)}</p>
                    <p className="hint">{located.climate_cached ? t('location.climateCached') : t('location.climateFetch')}</p>
                  </>
                )}
              </div>
            )}
          </section>

          <section className="panel" data-step="rotation">
            <h2>{t('rotation.title')}</h2>
            <p className="hint">{t('rotation.hint')}</p>
            <RotationBuilder crops={crops} entries={rotation} onChange={setRotation} />
          </section>

          <section className="panel" data-step="priorities">
            <h2>{t('priorities.title')}</h2>
            <p className="hint">{t('priorities.hint')}</p>
            <PrioritiesForm crops={crops} priorities={priorities} constraints={constraints} onPriorities={setPriorities} onConstraints={setConstraints} />
          </section>

          <div className="run">
            <button type="button" className="primary" disabled={running || !request} onClick={() => request && run(request, false)}>
              {running ? t('run.running') : t('run.button')}
            </button>
            {blocked && !running && <p className="hint warning-text" data-blocked>{blocked}</p>}
            <p className="hint">{t('app.disclaimer')}</p>
          </div>
        </aside>

        <main className="content">
          <MapPanel showcase={showcase} location={location} onPick={setLocation} />

          {running && (
            <div className="status" role="status" data-state="running">
              <span className="spinner" aria-hidden="true" />
              <div>
                <strong>{t('run.running')}</strong>
                <div className="muted">{t('run.progress')}</div>
              </div>
            </div>
          )}

          {error && !running && (
            <div className="status status-error" role="alert" data-state="error" data-error={error.code}>
              <span className="status-icon" aria-hidden="true">!</span>
              <div>
                <strong>{t(`error.${error.code}`)}</strong>
                {error.message && error.code !== 'network' && <div>{error.message}</div>}
              </div>
              <button type="button" className="secondary" onClick={() => lastRequest.current && run({ ...lastRequest.current, lang }, false)}>
                {t('run.retry')}
              </button>
            </div>
          )}

          {result && baseline && (
            <div className={running ? 'results results-stale' : 'results'} data-results>
              {result.meta.notices.length > 0 && (
                <ul className="notices">
                  {result.meta.notices.map((n, i) => (
                    <li key={`${n.code}-${i}`} data-notice={n.code}>{n.text}</li>
                  ))}
                </ul>
              )}
              <SiteDiagnosis site={result.site} baselineSlots={baseline.slots} cycleYears={baseline.cycle_years} groupOf={groupOf} />
              <StrategyCompare strategies={result.strategies} selectedId={selectedId} onSelect={setSelectedId} groupOf={groupOf} />
              {selected && <StrategyDetail strategy={selected} />}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
