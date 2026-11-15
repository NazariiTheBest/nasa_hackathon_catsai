import type { CropEntry, DayRef, Lang } from './api/client'

const LOCALE: Record<Lang, string> = { en: 'en-GB', uk: 'uk-UA' }

/** "12 Jul" for a day of year, in the interface language. */
export function dayLabel(doy: number, lang: Lang): string {
  const date = new Date(Date.UTC(2023, 0, doy)) // 2023 is not a leap year, like the engine's calendar
  return new Intl.DateTimeFormat(LOCALE[lang], { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(date)
}

/** Position of a calendar reference on the cycle, in days from the start of cycle year 0. */
export function cycleDay(ref: DayRef): number {
  return ref.year_index * 365 + ref.doy - 1
}

export function num(value: number, digits = 0, lang: Lang = 'en'): string {
  return new Intl.NumberFormat(LOCALE[lang], { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value)
}

export function signed(value: number, digits = 0, lang: Lang = 'en'): string {
  const text = num(Math.abs(value), digits, lang)
  if (Number(Math.abs(value).toFixed(digits)) === 0) return text
  return (value > 0 ? '+' : '−') + text
}

/** Colour group of a crop on the calendar strip: three hues that stay distinct for colour-blind readers. */
export type CropGroup = 'cereal' | 'broadleaf' | 'legume'

export function cropGroup(crop: CropEntry | undefined): CropGroup {
  if (!crop) return 'broadleaf'
  if (crop.family === 'poaceae') return 'cereal'
  if (crop.is_legume) return 'legume'
  return 'broadleaf'
}

export const OBJECTIVES = [
  'water',
  'nitrogen',
  'erosion',
  'organic_matter',
  'forage',
  'income',
  'resilience',
  'pest_break',
] as const
export type Objective = (typeof OBJECTIVES)[number]

export const PRIORITIES = ['water', 'nitrogen', 'erosion', 'organic_matter', 'forage', 'income'] as const
export type PriorityKey = (typeof PRIORITIES)[number]
