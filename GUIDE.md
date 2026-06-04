# Gödslingskollen — Complete Guide

## What It Does

**Gödslingskollen** is an interactive dashboard that monitors overfertilization risk on Swedish agricultural land. It combines satellite data (Sentinel-1, Sentinel-2), terrain data (EU-DTM), and national registries (LPIS, NMD) to produce field-level risk scores.

### The Problem

Swedish farmers apply nitrogen fertilizers to maximize yields. When more nitrogen is applied than crops can absorb, the excess:

- Leaches into groundwater as nitrate
- Runs off into lakes and the Baltic Sea, causing eutrophication (algal blooms, dead zones)
- Wastes money for the farmer
- Violates EU CAP cross-compliance regulations

Current monitoring is manual, sparse, and reactive — inspectors visit a tiny fraction of fields each year.

### The Solution

By analyzing satellite imagery every overpass (every 2-3 days for Sentinel-2), we can estimate how much nitrogen crops are actually using vs. how much was applied. Fields where crop nitrogen uptake is low despite high fertilizer application get flagged as **overfertilization risks**.

---

## How It Works — Step by Step

### 1. Data Ingestion

```
Sentinel-2 ──→ NDVI, NDRE, REIP (vegetation health / chlorophyll)
Sentinel-1 ──→ VV/VH backscatter change (manure spreading detection)
EU-DTM     ──→ Slope, flow accumulation (runoff risk)
LPIS       ──→ Parcel boundaries + declared crop type
NMD        ──→ Land cover mask (only score agricultural land)
```

### 2. Vegetation Indices

The dashboard computes three key indices per parcel:

| Index | Formula | What It Measures |
|---|---|---|
| **NDVI** | `(NIR - Red) / (NIR + Red)` | General greenness — proxy for plant health |
| **NDRE** | `(NIR - Red Edge) / (NIR + Red Edge)` | Canopy nitrogen — better for high-biomass crops |
| **REIP** | Red Edge Inflection Point | Chlorophyll content — directly linked to N uptake |

**Why red edge matters**: NDVI saturates when crops are dense (canopy closure). The red-edge bands (B05, B06, B07 on Sentinel-2) penetrate deeper into the canopy and remain sensitive to chlorophyll at high biomass. NDRE and REIP are therefore better indicators of crop nitrogen status in Swedish agriculture.

### 3. Manure Spreading Detection

When manure or slurry is spread, the soil surface texture and moisture change abruptly. Sentinel-1 SAR (C-band) detects this as a sudden shift in VV and VH backscatter. The algorithm flags parcels where backscatter changed more than 2 standard deviations from the 30-day rolling mean.

### 4. Runoff Risk

Using the EU Digital Terrain Model (25m resolution), we compute:

- **Slope percentage** — steeper slopes have higher runoff potential
- **Flow accumulation** — where water concentrates
- **Proximity to water bodies** — from NMD land cover

### 5. Risk Scoring

```
Risk = 0.40 × N_uptake_risk + 0.25 × Runoff_risk + 0.20 × Spreading_flag + 0.15 × Crop_factor

N_uptake_risk:  High when NDVI/NDRE is below crop-specific thresholds
                (crop isn't using available nitrogen)
Runoff_risk:    High when slope > 5% or near water bodies
Spreading_flag: 100 if S-1 detected recent spreading, else 0
Crop_factor:    Crop's typical nitrogen demand (wheat=0.85, ley=0.40, etc.)
```

### 6. Alert Levels

| Score | Label | Meaning |
|---|---|---|
| 0–30 | 🟢 Low | Crop is using applied nitrogen normally |
| 30–60 | 🟡 Moderate | Possible excess — monitor next pass |
| 60–80 | 🟠 High | Probable overfertilization — recommend inspection |
| 80–100 | 🔴 Critical | Confirmed overfertilization — notify municipality |

---

## File-by-File Breakdown

### `main.py` — Streamlit Entry Point

The dashboard application. Sets up the Streamlit page, calls each component, and manages the demo/real data flow. Key sections:

- **Page config**: Wide layout, custom CSS for Swedish theme (blue header)
- **Sidebar**: Municipality filter, date range, crop type, risk threshold, demo toggle
- **Summary panel**: Average risk, count of high/critical parcels, top 5 risks
- **Map panel**: pydeck interactive satellite map with color-coded parcels
- **Charts**: Plotly NDVI time series and risk score bar chart
- **Data table**: Full parcel data exportable as CSV

### `config.py` — Settings

- openEO backend URL and credentials (from environment variables)
- Default coordinates (Uppsala, Sweden)
- Crop nitrogen demand lookup table
- Risk model weights
- NDVI/NDRE thresholds

### `backend/sentinel.py` — openEO Satellite Access

Functions to query Sentinel-2, Sentinel-1, and EU-DTM data through the Copernicus Data Space Ecosystem. Each function:

1. Connects to openEO backend
2. Defines spatial extent (bounding box around target area)
3. Defines temporal extent (date range)
4. Selects relevant bands
5. Returns openEO DataCube for further processing

**Important**: These functions require valid openEO credentials set as environment variables (`OPENEO_USER`, `OPENEO_PASS`). Without them, the app falls back to demo mode.

### `backend/indices.py` — Vegetation Index Math

Pure NumPy functions for computing:

- `ndvi(nir, red)`: Normalized Difference Vegetation Index
- `ndre(nir, red_edge)`: Normalized Difference Red Edge
- `ci_green(nir, green)`: Chlorophyll Index Green
- `reip(b05, b06, b07)`: Red Edge Inflection Point (interpolation)

Also includes `zonal_mean()` for extracting parcel-level statistics from raster data and `compute_ndvi_timeseries()` for generating time series from openEO cubes.

### `backend/parcels.py` — LPIS Data Handling

Loads, filters, and converts agricultural parcel data:

- `load_parcels()`: Reads GeoJSON and extracts parcel metadata + geometry
- `filter_parcels()`: Filters by crop type, municipality
- `parcels_to_geojson()`: Re-serializes filtered parcels for map rendering

### `backend/risk.py` — Risk Scoring Engine

The core logic:

- `compute_risk_scores()`: Takes parcels + NDVI/NDRE values + spreading flags + slope and returns risk assessment per parcel
- `_n_uptake_risk()`: Compares actual vegetation indices to crop-specific thresholds
- `_runoff_risk()`: Maps slope percentage to categorical risk
- `risk_label()`: Converts numeric score to color-coded label

### `backend/data.py` — Demo Data Generator

When openEO is not available, generates realistic synthetic data:

- **Demo NDVI**: Each crop type gets a base NDVI (e.g., wheat=0.72, fallow=0.25) with a penalty for high declared N application
- **Demo NDRE**: Similar approach with lower baseline values
- **Demo slope**: Random slopes between 0.2–4.0%
- **Demo spreading**: ~25% of parcels randomly flagged
- **Demo time series**: 12 biweekly NDVI measurements with seasonal trend + noise

### `components/map.py` — Risk Map

Renders an interactive satellite-street map using pydeck. Parcels are colored by risk:

- **Green**: Low risk (< 30)
- **Yellow**: Moderate (30–60)
- **Orange**: High (60–80)
- **Red**: Critical (> 80)

Hovering or clicking a parcel shows a tooltip with parcel ID, crop, risk score, NDVI, NDRE, and applied nitrogen.

### `components/timeseries.py` — Time Series Charts

Two-panel Plotly figure:

- **Top**: NDVI over time for each parcel (different colored lines)
- **Bottom**: Bar chart of current risk scores, color-coded by severity

### `components/sidebar.py` — Filter Controls

Streamlit sidebar with:

- Municipality text input
- Date range picker
- Crop type dropdown (populated from `CROP_N_DEMAND`)
- Risk threshold slider
- Demo mode toggle
- Risk legend
- Refresh button

---

## How to Demo (Presentation Script)

### Opening (30 seconds)

> "This is Gödslingskollen — an overfertilization risk monitor for Swedish agriculture. It uses free satellite data from Copernicus to tell farmers and municipalities which fields are at risk of nutrient leaching."

### Show the Map (30 seconds)

> "Here are 10 agricultural parcels in **Svalöv municipality, Skåne** — Sweden's most productive agricultural region. They're color-coded by risk. Green is low risk, red is critical. Hover over any parcel — you'll see the crop type, current NDVI, and how much nitrogen was applied."

### Explain the Risk Logic (30 seconds)

> "The risk combines four factors: crop nitrogen uptake from Sentinel-2 imagery, manure spreading detection from Sentinel-1 radar, runoff potential from the digital terrain model, and the crop's known nitrogen demand from the LPIS registry."

### Show the Time Series (30 seconds)

> "Below, you can see NDVI over time for each parcel. Crops that stay green (high NDVI) are using nitrogen well. Crops with dropping NDVI despite high fertilizer input are our concern."

### The Demo Mode (15 seconds)

> "We have a demo mode with synthetic data so you can explore the dashboard right now. With openEO credentials, this connects to live satellite data from the Copernicus Data Space Ecosystem."

### Technical Summary (15 seconds)

> "Tech stack: Python, Streamlit for the dashboard, openEO for satellite data access, pydeck for the 3D map, Plotly for charts, and GeoPandas for parcel geometry."

---

## Setting Up for Real Data

To connect to live satellite data instead of demo mode:

```bash
export OPENEO_USER="your.email@example.com"
export OPENEO_PASS="your_password"
uv run streamlit run main.py
```

Then turn off "Use demo data" in the sidebar.

Get your free Copernicus Data Space Ecosystem account at: https://dataspace.copernicus.eu

---

## Extending the Prototype

Ideas for post-hackathon development:

- **Water proximity**: Add NMD water body layer to buffer zone compliance checks
- **Weather integration**: Include precipitation forecast to estimate leaching risk
- **Crop rotation**: Use previous year's LPIS data to check rotation compliance
- **Yield data**: Compare NDVI to historical yields to calibrate N-demand per field
- **Notifications**: Email/SMS alerts when parcels exceed thresholds
- **Multi-temporal**: Full growing season analysis with phenological stage tracking
- **Satellite tasking**: Trigger higher-resolution tasking (Planet, SPOT) for flagged parcels

---

## Data Sources & Credits

- **Sentinel-2 & Sentinel-1**: European Space Agency (ESA), Copernicus Programme
- **EU-DTM**: Copernicus Land Monitoring Service
- **LPIS**: Swedish Board of Agriculture (Jordbruksverket)
- **NMD**: Swedish Environmental Protection Agency (Naturvårdsverket)
- **openEO**: openEO API for cloud-based Earth observation processing
- **Built for**: Digital Earth Sweden Hackathon 2026
