import type { components } from './schema'

type Schemas = components['schemas']

export type Lang = 'en' | 'uk'
export type DataTier = 'field' | 'grid' | 'climate_only'
export type AnalyzeRequest = Schemas['AnalyzeRequest']
export type AnalyzeResponse = Schemas['AnalyzeResponse']
export type Strategy = Schemas['Strategy']
export type Slot = Schemas['Slot']
export type Site = Schemas['Site']
export type Evidence = Schemas['Evidence']
export type Statement = Schemas['Statement']
export type CropEntry = Schemas['CropEntry']
export type LocateResponse = Schemas['LocateResponse']
export type HealthResponse = Schemas['HealthResponse']
export type Priorities = Schemas['Priorities']
export type Constraints = Schemas['Constraints']
export type DayRef = Schemas['DayRef']

export interface ShowcaseFeature {
  type: 'Feature'
  properties: { unit_id: string; name: string | null; area_ha: number | null; bundle_id: string }
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon
}

export interface ShowcaseCollection {
  type: 'FeatureCollection'
  features: ShowcaseFeature[]
}

export type ApiErrorCode = 'climate_unavailable' | 'invalid_request' | 'network' | 'server_error'

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: ApiErrorCode,
    message: string,
  ) {
    super(message)
  }
}

interface ValidationItem {
  loc: (string | number)[]
  msg: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError(0, 'network', 'The server could not be reached.')
  }
  if (response.ok) return (await response.json()) as T

  let body: { code?: string; message?: string; detail?: ValidationItem[] } | null = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  if (response.status === 503 && body?.code === 'climate_unavailable') {
    throw new ApiError(503, 'climate_unavailable', body.message ?? '')
  }
  if (response.status === 422 && Array.isArray(body?.detail)) {
    const text = body.detail.map((d) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ')
    throw new ApiError(422, 'invalid_request', text)
  }
  // A dev proxy with no backend behind it answers 500/502/504 with no JSON body.
  if (response.status >= 500 && !body) throw new ApiError(response.status, 'network', 'The server could not be reached.')
  throw new ApiError(response.status, 'server_error', `HTTP ${response.status}`)
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  locate: (lat: number, lon: number) => request<LocateResponse>(`/api/locate?lat=${lat}&lon=${lon}`),
  crops: (lang: Lang) => request<Schemas['CropCatalog']>(`/api/crops?lang=${lang}`),
  showcase: () => request<ShowcaseCollection>('/api/showcase'),
  analyze: (body: AnalyzeRequest) =>
    request<AnalyzeResponse>('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}
