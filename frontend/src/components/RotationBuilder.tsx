import type { CropEntry } from '../api/client'
import { useT } from '../i18n'

export interface RotationEntry {
  crop: string
  cover: string | null
}

interface Props {
  crops: CropEntry[]
  entries: RotationEntry[]
  onChange: (entries: RotationEntry[]) => void
}

export default function RotationBuilder({ crops, entries, onChange }: Props) {
  const t = useT()
  const byId = new Map(crops.map((c) => [c.id, c]))
  const mains = crops.filter((c) => c.role !== 'cover').sort((a, b) => a.name.localeCompare(b.name))
  const covers = crops.filter((c) => c.role === 'cover').sort((a, b) => a.name.localeCompare(b.name))

  function move(index: number, by: number) {
    const next = [...entries]
    const [entry] = next.splice(index, 1)
    next.splice(index + by, 0, entry)
    onChange(next)
  }

  function update(index: number, patch: Partial<RotationEntry>) {
    onChange(entries.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)))
  }

  return (
    <div className="rotation">
      <ol className="rotation-list">
        {entries.map((entry, index) => {
          const crop = byId.get(entry.crop)
          return (
            <li key={`${entry.crop}-${index}`} className="rotation-item" data-crop={entry.crop}>
              <div className="rotation-row">
                <span className="rotation-index">{index + 1}</span>
                <span className="rotation-name">{crop?.name ?? entry.crop}</span>
                <span className="rotation-actions">
                  <button type="button" className="icon-button" title={t('rotation.up')} aria-label={t('rotation.up')}
                          disabled={index === 0} onClick={() => move(index, -1)}>
                    &uarr;
                  </button>
                  <button type="button" className="icon-button" title={t('rotation.down')} aria-label={t('rotation.down')}
                          disabled={index === entries.length - 1} onClick={() => move(index, 1)}>
                    &darr;
                  </button>
                  <button type="button" className="icon-button" title={t('rotation.remove')} aria-label={t('rotation.remove')}
                          onClick={() => onChange(entries.filter((_, i) => i !== index))}>
                    &times;
                  </button>
                </span>
              </div>
              <label className="rotation-cover">
                <span className="muted">{t('rotation.cover')}</span>
                <select value={entry.cover ?? ''} onChange={(e) => update(index, { cover: e.target.value || null })}>
                  <option value="">{t('rotation.noCover')}</option>
                  {covers.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            </li>
          )
        })}
      </ol>

      {entries.length === 0 && <p className="hint warning-text">{t('rotation.empty')}</p>}

      <label className="rotation-add">
        <span className="visually-hidden">{t('rotation.add')}</span>
        <select
          value=""
          disabled={entries.length >= 8}
          onChange={(e) => e.target.value && onChange([...entries, { crop: e.target.value, cover: null }])}
        >
          <option value="">+ {t('rotation.add')}</option>
          {mains.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
