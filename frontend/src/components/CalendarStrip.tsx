import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Slot } from '../api/client'
import { cycleDay, dayLabel, type CropGroup } from '../format'
import { useLang, useT } from '../i18n'

interface Tip {
  x: number
  y: number
  content: ReactNode
}

/** Hover and keyboard-focus tooltip shared by the charts. */
export function useTip() {
  const [tip, setTip] = useState<Tip | null>(null)
  const bind = (content: ReactNode) => ({
    onMouseEnter: (e: React.MouseEvent) => setTip({ x: e.clientX, y: e.clientY, content }),
    onMouseMove: (e: React.MouseEvent) => setTip({ x: e.clientX, y: e.clientY, content }),
    onMouseLeave: () => setTip(null),
    onFocus: (e: React.FocusEvent<HTMLElement>) => {
      const box = e.currentTarget.getBoundingClientRect()
      setTip({ x: box.left + box.width / 2, y: box.bottom, content })
    },
    onBlur: () => setTip(null),
  })
  const node = tip ? (
    <div className="tip" role="tooltip" style={{ left: Math.min(tip.x + 12, window.innerWidth - 260), top: tip.y + 14 }}>
      {tip.content}
    </div>
  ) : null
  return { bind, node }
}

interface Props {
  slots: Slot[]
  cycleYears: number
  groupOf: (cropId: string) => CropGroup
}

interface Segment {
  slot: Slot
  left: number
  width: number
  cutStart: boolean
  cutEnd: boolean
}

function segments(slots: Slot[], total: number): Segment[] {
  const out: Segment[] = []
  for (const slot of slots) {
    const start = cycleDay(slot.sow)
    const end = start + slot.days
    if (end <= total) {
      out.push({ slot, left: start, width: slot.days, cutStart: false, cutEnd: false })
    } else {
      // The slot wraps around the end of the repeating cycle: draw both parts.
      out.push({ slot, left: start, width: total - start, cutStart: false, cutEnd: true })
      out.push({ slot, left: 0, width: end - total, cutStart: true, cutEnd: false })
    }
  }
  return out
}

/** A rotation on its repeating cycle: main crops as bars, cover crops as a thin bar beneath, gaps as bare soil. */
export default function CalendarStrip({ slots, cycleYears, groupOf }: Props) {
  const t = useT()
  const lang = useLang()
  const { bind, node } = useTip()
  const total = cycleYears * 365
  const mains = segments(slots.filter((s) => s.role === 'main'), total)
  const covers = segments(slots.filter((s) => s.role === 'cover'), total)
  const pct = (days: number) => `${(days / total) * 100}%`

  const render = (seg: Segment, i: number, kind: 'main' | 'cover') => {
    const { slot } = seg
    const label = `${slot.crop_name}: ${dayLabel(slot.sow.doy, lang)} → ${dayLabel(slot.harvest.doy, lang)}, ${slot.days} ${t('site.bare.days')}`
    return (
      <div
        key={`${kind}-${i}`}
        className={`seg seg-${kind} seg-${groupOf(slot.crop_id)}${seg.cutStart ? ' cut-start' : ''}${seg.cutEnd ? ' cut-end' : ''}`}
        style={{ left: pct(seg.left), width: pct(seg.width) }}
        tabIndex={0}
        aria-label={label}
        {...bind(
          <>
            <strong>{slot.crop_name}</strong>
            {kind === 'cover' && <span className="muted"> ({t('detail.cover')})</span>}
            <br />
            {dayLabel(slot.sow.doy, lang)} &rarr; {dayLabel(slot.harvest.doy, lang)} &middot; {slot.days} {t('site.bare.days')}
          </>,
        )}
      />
    )
  }

  return (
    <div className="strip" role="img" aria-label={slots.map((s) => s.crop_name).join(', ')}>
      <div className="strip-track strip-main">
        {Array.from({ length: cycleYears - 1 }, (_, i) => (
          <span key={i} className="strip-year-line" style={{ left: pct((i + 1) * 365) }} />
        ))}
        {mains.map((seg, i) => render(seg, i, 'main'))}
      </div>
      {covers.length > 0 && <div className="strip-track strip-cover">{covers.map((seg, i) => render(seg, i, 'cover'))}</div>}
      <div className="strip-years">
        {Array.from({ length: cycleYears }, (_, i) => (
          <span key={i} style={{ width: pct(365) }}>
            {t('strategies.year')} {i + 1}
          </span>
        ))}
      </div>
      {node}
    </div>
  )
}
