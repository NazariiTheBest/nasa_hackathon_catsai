# Project Context: Field Shift — Adapting Farms with NASA Data
**Event:** 2026 NASA Space Apps Challenge (48-Hour Hackathon)
**Current Status:** Greenfield (starting from scratch — architecture and implementation need to be designed).

---

## 1. CRITICAL FIRST STEP: Hardware & Environment Assessment (MCP)
Before proposing any software architecture, data processing pipelines, or machine learning models, **you MUST call the `laptop-specs-server` MCP tool** to inspect the host system's hardware capabilities (CPU, RAM, GPU/VRAM, OS, and available disk space).
- Tailor all local data processing, batch sizes, raster handling, and ML model choices strictly to the hardware constraints returned by `laptop-specs-server`.
- Avoid proposing heavy local deep learning or massive in-memory raster operations if they exceed local VRAM/RAM limits or cannot be executed rapidly within a 48-hour hackathon window.

---

## 2. Team Structure & Role Division
We are a 3-person team:
1. **ML / Backend / System Architect (Current User):** Responsible for system architecture, backend API (Python/FastAPI), ML/Statistical modeling (SI), data fusion logic, and the interactive Decision-Support UI.
2. **Geospatial Scientist #1:** Responsible for raw EO satellite data extraction, spatial/temporal resolution harmonization, and exporting clean features/rasters/GeoJSONs.
3. **Geospatial Scientist #2:** Responsible for agronomic indices calculation (NDVI, EVI, anomalies), GIS visualization layers, and scientific validation of rotation scenarios.

*Note for Agent:* Design the architecture with clean data contracts (e.g., JSON/CSV/Parquet/GeoJSON schemas) so the ML/Backend system can seamlessly ingest pre-processed spatial features from the Geospatial Scientists, OR fetch lightweight tabular data directly via APIs (like NASA POWER).

---

## 3. Challenge Overview & Core Problem
Farmers face shifting temperatures, unpredictable rainfall, water shortages, extreme weather, and declining soil health. Selecting new crops for rotation is risky because a crop that improves soil health in one area might consume too much water, fall outside growing seasons, or lack market viability elsewhere.

**Goal:** Create a practical, farmer-centered **Decision-Support Tool** (web app, interactive map, and/or modeling pipeline) that fuses NASA Earth observations with local soil data, crop characteristics, and farmer priorities to recommend and compare resilient crop-rotation strategies.

---

## 4. Mandatory Functional Requirements (MVP Scope)
To score highly with NASA judges, the system MUST accomplish the following:
1. **User Inputs:** Allow a farmer/user to select a field location (coordinates/polygon or region), specify their current crop/rotation, and set priorities/constraints (e.g., water conservation, nitrogen fixation, erosion reduction, organic matter improvement, forage value, or market income).
2. **Multi-Source Data Fusion & SI Modeling:** Combine satellite climate/vegetation indicators with soil properties to detect:
   - Times when fields are typically bare (bare-soil exposure risk).
   - Seasons when current crops show heightened vulnerability (heat, drought, or frost stress).
   - Long-term trends in water balance, soil moisture, and temperature.
3. **Compare At Least 3 Rotation Strategies:** 
   - Strategy 1: Baseline (Existing Rotation).
   - Strategy 2 & 3+: Alternative resilient rotation strategies (e.g., integrating cover crops, nitrogen-fixing legumes, deep-rooting or drought-tolerant crops).
4. **Explainable Output per Strategy:** For every suggested rotation, explicitly output:
   - **Why it was suggested** (alignment with farmer priorities & climate trends).
   - **Supporting Evidence** (specific NASA indicators/metrics backing the choice).
   - **Expected Benefits** (water saved, pest-cycle disruption, erosion control, soil health).
   - **Information Gaps & Uncertainty** (model confidence, spatial resolution limits).
   - **Risks Requiring Local Review** (reminders that the tool supports—not replaces—farmer judgment and local agronomists).

---

## 5. Available NASA & Partner Datasets Reference
When designing the data pipeline, select the most practical combination of these official challenge datasets (prioritize accessible APIs and pre-aggregated layers for the 48h MVP):

### NASA & Partner Earth Observation (EO) & Climate
- **NASA POWER (Agroclimatology API):** High-priority for fast tabular time-series! Solar, temperature, humidity, precipitation, radiation, frost risk, and crop water-use indicators.
- **SMAP (Soil Moisture Active Passive):** Surface soil moisture & freeze/thaw every 2–3 days. Identifies drought stress, infiltration, and water availability.
- **GPM & IMERG:** Global precipitation rates, extreme storm frequency, rainfall reliability, and erosion risk.
- **Landsat (30m), MODIS/VIIRS (250–1000m), & ESA Copernicus Sentinel-2 (10–20m):** Surface reflectance, NDVI/EVI vegetation indices, bare-ground detection, seasonal transitions, and crop vigor.
- **ECOSTRESS & OpenET:** High-res Land Surface Temperature (LST) and Evapotranspiration (ET) for thermal stress hotspots and crop water demand.
- **SRTM (Shuttle Radar Topography Mission):** Elevation, slope, water runoff, and terrain-driven erosion risk.
- **NLDAS / GLDAS & ECMWF ERA5:** Continuous gridded time-series of soil moisture, temperature, wind, and evapotranspiration proxies.
- **GRACE / GRACE-FO:** Long-term groundwater and water-storage trends.
- **GEDI:** Laser-based canopy structure and above-ground biomass around agricultural landscapes.

### Agricultural, Soil & Ground-Truth Context
- **FAO Global Agro-Ecological Zones (GAEZ):** Global crop suitability layers, soil constraints, and yield potentials (great for global/Ukrainian or multi-region compatibility).
- **USDA NRCS WSS & SSURGO/STATSGO2:** Detailed U.S. soil properties (texture, organic matter, drainage class, water-holding capacity, erosion risk).
- **USDA Cropland Data Layer (CDL / CropScape) & NAIP (1m aerial) & USGS NLCD:** Historical crop types, field boundaries, and land-cover context.
- **PRISM Climate Data & CoCoRaHS & USGS NWIS:** High-res U.S. climate normals, crowd-sourced rain validation, and groundwater/streamflow records.
- **USDA Ag Data Commons, NASS QuickStats & AMS Market News:** Historical county yields, crop phenology, and commodity market prices/viability.
- **USFS LANDFIRE:** Surrounding landscape vegetation and ecosystem context.

---

## 6. Agent Instructions for Architecture & Exploration
When I run `/openspec-explore` or ask for architectural planning, follow these steps:
1. **Run `laptop-specs-server` first** and summarize my hardware constraints.
2. **Propose a pragmatic 48-hour MVP Architecture:**
   - Suggest the fastest, highest-impact tech stack (e.g., Python backend, lightweight ML/scoring engine, interactive frontend with map & comparison dashboard).
   - Define how we will harmonize/ingest data without getting bogged down in terabytes of raw satellite downloads (e.g., combining live **NASA POWER API** + pre-extracted **Sentinel-2/MODIS/SMAP** stats from our Geospatial Scientists + an agronomic crop-trait knowledge base).
3. **Design the SI / Recommendation Engine:** Propose a clear, explainable mathematical/ML approach (e.g., multi-objective scoring + gradient boosting or rule-constrained optimization) that evaluates rotation sequences and outputs the required explanations, uncertainties, and risk flags.
4. Keep communication concise, technical, and action-oriented. Wait for my approval before generating full OpenSpec change proposals.