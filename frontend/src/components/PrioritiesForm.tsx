import type { Constraints, CropEntry, Priorities } from '../api/client'
import { PRIORITIES } from '../format'
import { useT } from '../i18n'

interface Props {
  crops: CropEntry[]
  priorities: Priorities
  constraints: Required<Constraints>
  onPriorities: (priorities: Priorities) => void
  onConstraints: (constraints: Required<Constraints>) => void
}

export default function PrioritiesForm({ crops, priorities, constraints, onPriorities, onConstraints }: Props) {
  const t = useT()
  const excluded = new Set(constraints.excluded_crops)
  const candidates = [...crops].sort((a, b) => a.name.localeCompare(b.name))

  function toggleExcluded(id: string) {
    const next = new Set(excluded)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onConstraints({ ...constraints, excluded_crops: [...next] })
  }

  return (
    <div className="priorities">
      <div className="sliders">
        {PRIORITIES.map((key) => {
          const value = priorities[key]
          return (
            <label key={key} className="slider">
              <span className="slider-label">{t(`priority.${key}`)}</span>
              <input
                type="range" min={0} max={1} step={0.1} value={value} data-priority={key}
                onChange={(e) => onPriorities({ ...priorities, [key]: Number(e.target.value) })}
              />
              <output className="slider-value">{value === 0 ? t('priorities.off') : Math.round(value * 10)}</output>
            </label>
          )
        })}
      </div>

      <h3>{t('constraints.title')}</h3>
      <label className="check">
        <input
          type="checkbox" checked={constraints.irrigation_available}
          onChange={(e) => onConstraints({ ...constraints, irrigation_available: e.target.checked })}
        />
        <span>{t('constraints.irrigation')}</span>
      </label>
      <label className="inline-field">
        <span>{t('constraints.maxCycle')}</span>
        <input
          type="number" min={1} max={8} value={constraints.max_cycle_years}
          onChange={(e) => onConstraints({ ...constraints, max_cycle_years: Math.min(8, Math.max(1, Number(e.target.value) || 1)) })}
        />
      </label>
      <details className="exclude">
        <summary>
          {t('constraints.exclude')}
          {excluded.size > 0 && <span className="count-badge">{excluded.size} {t('constraints.excluded')}</span>}
        </summary>
        <div className="exclude-list">
          {candidates.map((crop) => (
            <label key={crop.id} className="check">
              <input type="checkbox" checked={excluded.has(crop.id)} data-exclude={crop.id} onChange={() => toggleExcluded(crop.id)} />
              <span>{crop.name}</span>
            </label>
          ))}
        </div>
      </details>
    </div>
  )
}
