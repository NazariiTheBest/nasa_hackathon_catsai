import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import type { ShowcaseCollection, ShowcaseFeature } from '../api/client'
import { dayLabel } from '../format'
import { useLang, useT } from '../i18n'

// NASA GIBS, layer and tile matrix set as listed in the GIBS WMTS capabilities document.
const GIBS_LAYER = 'MODIS_Terra_L3_NDVI_16Day'
const GIBS_DATE = '2025-06-26' // start of a 16-day composite near peak season
const GIBS_URL = `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${GIBS_LAYER}/default/${GIBS_DATE}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png`
const GIBS_LEGEND = 'https://gibs.earthdata.nasa.gov/legends/MODIS_L3_NDVI_H.svg'
const UKRAINE_CENTER: [number, number] = [48.8, 31.4]

export interface PickedLocation {
  kind: 'point' | 'unit'
  lat: number
  lon: number
  unitId?: string
  name?: string | null
}

interface Props {
  showcase: ShowcaseCollection | null
  location: PickedLocation | null
  onPick: (location: PickedLocation) => void
}

function ClickToPick({ onPick }: { onPick: Props['onPick'] }) {
  useMapEvents({
    click(event) {
      onPick({ kind: 'point', lat: round(event.latlng.lat), lon: round(event.latlng.lng) })
    },
  })
  return null
}

function FlyTo({ bounds }: { bounds: L.LatLngBounds | null }) {
  const map = useMap()
  useEffect(() => {
    if (bounds) map.flyToBounds(bounds, { maxZoom: 13, duration: 0.6, padding: [40, 40] })
  }, [bounds, map])
  return null
}

function round(value: number): number {
  return Math.round(value * 10000) / 10000
}

export default function MapPanel({ showcase, location, onPick }: Props) {
  const t = useT()
  const lang = useLang()
  const [layerOn, setLayerOn] = useState(false)
  const [layerFailed, setLayerFailed] = useState(false)
  const [target, setTarget] = useState<L.LatLngBounds | null>(null)
  const tiles = useRef({ loaded: 0, failed: 0 })

  const showcaseBounds = useMemo(
    () => (showcase && showcase.features.length ? L.geoJSON(showcase as GeoJSON.GeoJsonObject).getBounds() : null),
    [showcase],
  )

  function toggleLayer(on: boolean) {
    tiles.current = { loaded: 0, failed: 0 }
    setLayerFailed(false)
    setLayerOn(on)
  }

  return (
    <div className="map-wrap">
      <MapContainer center={UKRAINE_CENTER} zoom={6} minZoom={4} className="map" scrollWheelZoom>
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
        {layerOn && (
          <TileLayer
            url={GIBS_URL}
            opacity={0.75}
            maxNativeZoom={9}
            attribution='Imagery: <a href="https://earthdata.nasa.gov/gibs">NASA EOSDIS GIBS</a>, MODIS Terra NDVI'
            eventHandlers={{
              tileload: () => {
                tiles.current.loaded += 1
                setLayerFailed(false)
              },
              tileerror: () => {
                tiles.current.failed += 1
                if (tiles.current.loaded === 0 && tiles.current.failed >= 2) setLayerFailed(true)
              },
            }}
          />
        )}
        {showcase && (
          <GeoJSON
            key={showcase.features.length}
            data={showcase as GeoJSON.GeoJsonObject}
            style={(feature) => {
              const selected = location?.kind === 'unit' && feature?.properties?.unit_id === location.unitId
              return {
                color: selected ? '#0b0b0b' : '#104281',
                weight: selected ? 3 : 2,
                fillColor: '#2a78d6',
                fillOpacity: selected ? 0.35 : 0.15,
              }
            }}
            onEachFeature={(feature, layer) => {
              const f = feature as unknown as ShowcaseFeature
              layer.bindTooltip(f.properties.name ?? f.properties.unit_id, { sticky: true })
              layer.on('click', (event) => {
                L.DomEvent.stopPropagation(event)
                const bounds = (layer as L.Polygon).getBounds()
                const center = bounds.getCenter()
                onPick({ kind: 'unit', lat: round(center.lat), lon: round(center.lng), unitId: f.properties.unit_id, name: f.properties.name })
                setTarget(bounds)
              })
            }}
          />
        )}
        {location?.kind === 'point' && (
          <CircleMarker
            center={[location.lat, location.lon]}
            radius={8}
            pathOptions={{ color: '#fcfcfb', weight: 2, fillColor: '#0b0b0b', fillOpacity: 1 }}
          />
        )}
        <ClickToPick onPick={onPick} />
        <FlyTo bounds={target} />
      </MapContainer>

      <div className="map-controls">
        <label className="check">
          <input type="checkbox" checked={layerOn} onChange={(e) => toggleLayer(e.target.checked)} />
          <span>{t('map.layer')}</span>
        </label>
        {layerOn && !layerFailed && (
          <div className="map-legend">
            <img src={GIBS_LEGEND} alt="NDVI" />
            <span className="muted">
              {t('map.layerDate')} {dayLabel(177, lang)} 2025
            </span>
          </div>
        )}
        {layerOn && layerFailed && (
          <p className="map-warning" role="status">
            {t('map.layerFailed')}
          </p>
        )}
        {showcaseBounds && (
          <button type="button" className="link-button" onClick={() => setTarget(L.latLngBounds(showcaseBounds.getSouthWest(), showcaseBounds.getNorthEast()))}>
            {t('location.zoomShowcase')}
          </button>
        )}
      </div>
    </div>
  )
}
