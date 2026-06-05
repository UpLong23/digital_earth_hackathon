# WOFOST Crop Model & SoilGrids Pipeline

This document explains how WOFOST works conceptually, how SoilGrids data is fetched and converted for WOFOST, and how the entire pipeline fits together in Gödslingskollen.

---

## 1. What Is WOFOST?

**WFO**rld **FO**od **ST**udies is a dynamic, mechanistic crop growth model developed by Wageningen University (now maintained as part of the **PCSE** — Python Crop Simulation Environment — library). It simulates daily crop development from sowing to maturity driven by:

- **Weather** (radiation, temperature, precipitation, evaporation, wind)
- **Soil** (water holding capacity, rooting depth, infiltration)
- **Crop parameters** (phenology, leaf area expansion, light interception, dry matter partitioning, harvest index)

WOFOST operates at three production levels:

| Level | Full Name | Constraints Considered |
|-------|-----------|----------------------|
| **PP** | Potential Production | Only temperature & radiation (no water/nutrient limits) |
| **WLP** | Water-Limited Production | + soil water balance (rainfall, irrigation, evapotranspiration) |
| **NWLP** | Nutrient & Water-Limited Production | + soil nitrogen & nutrient uptake |

Gödslingskollen auto-detects the model variant in order: `Wofost80_NWLP_FD_beta` → `Wofost80_WLP_FD_beta` → `Wofost72_WLP_FD`. At Swedish latitutes, typically `Wofost72_WLP_FD` is used (NWLP requires additional N routines not always available).

### 1.1 Daily Simulation Loop

For each day of the growing season, WOFOST processes:

```
DAY d:
  1. Compute development stage (DVS) from temperature sum
  2. Compute LAI from DVS & assimilate partitioning
  3. Intercept radiation (Beer's law: I = I₀ × (1 − e^(−k×LAI)))
  4. Compute gross photosynthesis (leaf-level CO₂ assimilation)
  5. Maintenance respiration (function of biomass & temperature)
  6. Growth respiration (conversion efficiency ~0.7)
  7. Partition net dry matter → roots, stems, leaves, storage organs
  8. Soil water balance (rainfall in, evapotranspiration out, percolation, capillary rise)
  9. If water stress: reduce expansion growth, stomatal conductance, senescence
  10. Repeat until DVS ≥ 2.0 (maturity)
```

**Key output variables**:

| Symbol | Description | Unit |
|--------|-------------|------|
| TWSO | Total Weight of Storage Organs (yield) | kg/ha (dry matter) |
| TAGP | Total Above-Ground Production (biomass) | kg/ha |
| LAI | Leaf Area Index | m²/m² |
| TRA | Transpiration | mm |
| DVS | Development Stage | 0 (emergence) → 2 (maturity) |
| SM | Soil Moisture in root zone | cm³/cm³ |

The final yield reported in Gödslingskollen is `TWSO × 1000` to convert to fresh weight kg/ha (crop parameters are in dry matter; the ×1000 scales from PCSE's internal units).

### 1.2 Phenology & Temperature Sums

WOFOST is a **thermal-time** model. Development rate is driven by **Temperature Sum** (growing-degree-days, GDD):

```
TSUM = ∑ max(0, T_mean − T_base)
```

Key crop parameters:

| Parameter | Meaning | Typical value (winter wheat) |
|-----------|---------|------------------------------|
| TSUM1 | Temperature sum from emergence to anthesis | 1250 °C·d |
| TSUM2 | Temperature sum from anthesis to maturity | 750 °C·d |
| TBASE | Base temperature for development | 0 °C |
| TEFFMX | Maximum effective temperature | 30 °C |
| DLO | Optimal day length for vernalization | 12 h |
| VERNSAT | Saturation vernalization days | 30 d |

**Why WOFOST yields 0 at Swedish latitudes**: The default TSUM1/TSUM2 parameters in the WOFOST72 crop files are calibrated for Dutch/continental climates (52°N). At 62°N in Sweden, the growing season temperature sum rarely reaches the required threshold before September frost, so the crop never reaches maturity and `TWSO = 0`. Swedish-calibrated parameters require lower TSUM1/TSUM2 values.

### 1.3 Light Interception & Photosynthesis

WOFOST uses a **big-leaf** canopy model:

```
I_intercepted = I_0 × (1 − e^(−K_ext × LAI))

Gross assimilation rate (leaf level):
  A_leaf = A_max × tanh(I_absorbed × E_quantum / A_max)

Canopy assimilation:
  A_canopy = ∫ A_leaf(LAI) d(LAI)  (Gaussian integration over 3 canopy layers)
```

Where:
- `K_ext` = extinction coefficient (~0.6 for cereals)
- `A_max` = maximum leaf CO₂ assimilation rate (kg CO₂/ha/hr)
- `E_quantum` = initial light use efficiency (kg CO₂/J)

### 1.4 Dry Matter Partitioning

Partitioning fractions change over development:

```
DVS 0.0 → 0.3:  roots=0.4, stems=0.3, leaves=0.3, storage=0.0
DVS 0.3 → 1.0:  roots=0.1, stems=0.3, leaves=0.2, storage=0.4
DVS 1.0 → 2.0:  roots=0.0, stems=0.0, leaves=-0.2, storage=1.2
```

(Values illustrative; exact fractions defined per crop+variety in YAML.)

### 1.5 Soil Water Balance

WOFOST uses a **tipping-bucket** water balance with soil layers:

```
SoilWater(d+1) = SoilWater(d) + Rain + Irrigation − Runoff − Drainage − Transpiration − SoilEvaporation

Drainage = max(0, SoilWater − SMFCF) / (SOPE × Δt)  (simple drainage rate)
Runoff   = f(slope, rainfall intensity, surface storage)
Stress   = f(SM / (SMFC − SMWP))  →  reduction factor 0-1 on photosynthesis/expansion
```

| Parameter | Meaning | Typical value |
|-----------|---------|---------------|
| SMW | Soil moisture at wilting point | 0.12 cm³/cm³ |
| SMFCF | Soil moisture at field capacity | 0.30 cm³/cm³ |
| S0 | Soil moisture at saturation | 0.40 cm³/cm³ |
| CRAIRC | Critical air content for root aeration | 0.05 |
| SOPE | Maximum percolation rate | 10 cm/day |
| KSUB | Maximum capillary rise rate | 1.0 mm/day |
| WAV | Available water in root zone | 150 mm |

---

## 2. Crop Parameters: YAML Files

WOFOST crop parameters are stored as YAML files—one per crop, with multiple variety sub-entries. They are cloned from:

```
https://github.com/ajwdewit/WOFOST_crop_parameters  (branch: wofost72)
```

Installed at: `/tmp/WOFOST_crop_parameters/` (23 crops).

**File structure** (e.g., `winter_wheat.yaml`):

```yaml
WinterWheat
  default:
    TSUM1: 1250
    TSUM2: 750
    TBASE: 0.0
    TEFFMX: 30.0
    DLO: 12.0
    VERNSAT: 30.0
    AMAXTB: [[0.00, 35.0], [0.50, 40.0], [1.00, 38.0], [1.50, 30.0], [2.00, 20.0]]
    FRTB: [[0.00, 0.40], [0.30, 0.20], [0.60, 0.15], [1.00, 0.10], [1.50, 0.05], [2.00, 0.00]]
    FSTB: [[0.00, 0.30], [0.30, 0.35], [0.60, 0.35], [1.00, 0.30], [1.50, 0.10], [2.00, 0.00]]
    FOTB: [[0.00, 0.30], [0.30, 0.45], [0.60, 0.50], [1.00, 0.60], [1.50, 0.85], [2.00, 1.00]]
    FLTB: [[0.00, 0.30], [0.30, 0.45], [0.60, 0.50], [1.00, 0.60], [1.50, 0.85], [2.00, 1.00]]
    KDIFF: 0.6
    EFF: 0.45
    CVL: 0.685
    CVO: 0.700
    CVR: 0.694
    CVS: 0.665
    ...
```

**File loading**: PCSE's `YAMLCropDataProvider(model=Wofost72_WLP_FD, fpath="/tmp/WOFOST_crop_parameters", force_reload=False)` reads every `.yaml` file in the directory. Crops are indexed by their top-level YAML key; varieties are sub-keys. The first load parses all YAML; subsequent loads use a pickle cache at `YAMLCropDataProvider.pkl`.

**CropResolver** (`backend/wofost.py:63`): Maps LPIS crop labels (e.g., "Spring Barley") to YAML crop keys (e.g., "barley" → variety "spring_barley"). Uses a cascade: exact match → synonym lookup → seasonal qualifier removal → substring → fuzzy token overlap. 17 built-in Swedish crops as fallback if YAML files unavailable.

**Thread safety**: `run_single_wofost()` creates a fresh `YAMLCropDataProvider` per thread because PCSE's `set_active_crop()` modifies internal state. The pickle cache makes this cheap (~0.01 s).

---

## 3. SoilGrids Pipeline

### 3.1 What Is SoilGrids?

SoilGrids is a **global gridded soil information system** at ~250 m resolution, produced by ISRIC — World Soil Information. It predicts soil properties at six standard depths (0–5, 5–15, 15–30, 30–60, 60–100, 100–200 cm) using:

- ~150,000 field profile observations (from national soil databases, WoSIS)
- Environmental covariates: terrain (DEM, slope), climate (precipitation, temperature), land cover, lithology
- Machine learning: **quantile regression forest** (Random Forest variant)

Properties available (queried in Gödslingskollen):

| Property | Depth | Unit | In app |
|----------|-------|------|--------|
| `clay` | 0–5 cm | % (mass) | → Clay content for soil classification |
| `sand` | 0–5 cm | % (mass) | → Sand content for leaching risk |
| `silt` | 0–5 cm | % (mass) | → Silt content |
| `bulkdensity` | 0–5 cm | kg/m³ | → Bulk density (converted to g/cm³) |
| `phh2o` | 0–5 cm | pH units | → Soil acidity |
| `nitrogen` | 0–5 cm | mg/kg | → Nitrogen content for N budget |
| `soc` | 0–5 cm | g/kg | → Soil organic carbon |

### 3.2 API Query

**Endpoint**: `https://rest.isric.org/soilgrids/v2.0/properties/query`

**Query format**:
```
GET /?property=clay&property=sand&property=silt&property=bulkdensity&property=phh2o&property=nitrogen&property=soc&lat=62.0&lon=15.0&depth=0-5cm&value=mean
```

**Response** (simplified):
```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [15.0, 62.0] },
  "properties": {
    "layers": [
      {
        "name": "clay",
        "unit_measure": { "unit": "kg/kg", "mapped_value": "g/kg" },
        "depths": [{
          "label": "0-5cm",
          "values": { "mean": 250 }
        }]
      },
      ...
    ]
  }
}
```

Values are returned in **g/kg** (except bulkdensity in kg/m³, phh2o unitless).

### 3.3 Conversion to WOFOST Parameters

`_to_wofost_soil()` in `backend/soil.py:68` performs these conversions:

```
clay_frac  = clay_gkg  / 1000    (250 → 0.25 fractional)
sand_frac  = sand_gkg  / 1000
silt_frac  = silt_gkg  / 1000
bd_gcm3    = buldensity_kgm3 / 1000   (1400 → 1.4 g/cm³)
n_gkg      = nitrogen_mgkg / 1000     (1500 → 1.5 g/kg)
soc_pct    = soc_gkg    / 10          (15 → 1.5%)
```

**Soil water parameters** are approximated from clay content using empirical thresholds. This is a crude but functional approach:

| Clay fraction | SMW (wilting point) | SMFCF (field capacity) | S0 (saturation) |
|--------------|--------------------|----------------------|----------------|
| > 0.35       | 0.20               | 0.40                 | 0.45           |
| 0.20–0.35    | 0.12               | 0.30                 | 0.40           |
| 0.10–0.20    | 0.08               | 0.24                 | 0.38           |
| < 0.10       | 0.04               | 0.18                 | 0.35           |

These approximate the **Van Genuchten-Mualem** water retention model at three key points (wilting point at pF 4.2, field capacity at pF 2.0, saturation at pF 0).

Available water capacity: `AWC = SMFCF − SMW`

### 3.4 Fallback Defaults

When SoilGrids query fails (timeout, no data at high latitudes), the app falls back to **conservative Swedish mineral soil defaults**:

```python
DEFAULT_SOIL = {
    "clay": 0.25, "sand": 0.40, "silt": 0.35,
    "bulk_density": 1.4, "ph": 6.2,
    "available_water_capacity": 0.15,
    "soc": 1.5, "nitrogen": 0.15,
    "source": "default_swedish", "fallback": True,
}
```

These represent an average Swedish agricultural mineral soil (moderate clay, slightly acidic, moderate organic carbon).

### 3.5 Cache

Soil data is cached locally as JSON for **7 days** (keyed by rounded lat/lon to 2 decimal places, i.e., ~11 km grid). This avoids repeated API calls for the same location.

---

## 4. Complete WOFOST Pipeline in Gödslingskollen

### 4.1 Resource Preparation (`_prepare_wofost_bundle`)

Called **once per query** (not per parcel). Creates all shared resources:

1. **Detect model**: tries `Wofost80_NWLP_FD_beta` → `Wofost80_WLP_FD_beta` → `Wofost72_WLP_FD`.
2. **Load crop YAML**: `YAMLCropDataProvider(model, fpath)` — reads all 23 crop files.
3. **Build weather provider** (`_build_weather_provider`):
   - Open-Meteo daily DataFrame → list of `WeatherDataContainer` objects.
   - For each day compute `E0`, `ES0`, `ET0` via PCSE's `reference_ET()` (Penman-Monteith derived).
   - Clamp to PCSE trait ranges (0–2.5 mm/day).
4. **Select site provider class**: `WOFOST72SiteDataProvider` / `WOFOST73SiteDataProvider` / `WOFOST81SiteDataProvider_Classic` by model version.
5. **Set soil parameters**: SMFCF, SM0, SMW, CRAIRC, K0, SOPE, KSUB, RDMSOL.

Returns a dict (the "bundle") passed to every per-parcel runner.

### 4.2 Per-Parcel Run (`run_single_wofost`)

Called from `ThreadPoolExecutor(max_workers=8)` — up to 8 parcels simulated in parallel.

Step by step:

```
1. Resolve crop label (LPIS → WOFOST crop + variety)
   └─ If crop_name is None (fallow/unknown) → heuristic result, return

2. Determine sowing date
   └─ SWEDISH_SOWING_DEFAULTS dict (e.g., spring barley → April 25)
   └─ User can override via sidebar

3. Create thread-local YAMLCropDataProvider
   └─ Same model, same fpath, force_reload=False
   └─ Pickle cache makes this fast (~0.01 s)

4. Find YAML crop name + variety
   └─ Substring match on provider._store keys
   └─ Variety selected by season hint (winter/spring) → default → first

5. crop_provider.set_active_crop(yaml_crop_name, yaml_variety)

6. Create SiteDataProvider(WAV=available_water_capacity_mm)

7. Build ParameterProvider(sitedata=site, soildata=soil_params, cropdata=crop_provider)

8. Build agro management list:
   [{
     season_start: {
       "CropCalendar": {
         crop_name, variety_name,
         crop_start_date: sowing_date,
         crop_start_type: "sowing",
         crop_end_type: "maturity",
         max_duration: N days
       },
       "TimedEvents": None,
       "StateEvents": None,
     }
   }]

9. model = model_cls(params, weather_provider, agro)

10. sim_end = min(season_end, weather_provider.last_date)
    model.run_till(sim_end.isoformat())

11. output = model.get_output()

12. Extract:
    yield_kg_ha = output[-1]["TWSO"] × 1000
    biomass_kg_ha = output[-1]["TAGP"] × 1000
    peak_lai = max(output["LAI"])
    transpiration_mm = sum(output["TRA"])
    daily_df = _output_to_dataframe(output)

13. Return result dict (or fall back to heuristic on error)
```

### 4.3 Heuristic Fallback (`_heuristic_result`)

When WOFOST is unavailable, fails, or crop has no YAML file:

```
base_yield = CROP_BASE_YIELDS[crop_name]   # e.g., potato → 35000 kg/ha
lat_factor = max(0.5, 1.0 − (|lat| − 55) × 0.03)
season_factor = n_days / 150
yield = base_yield × lat_factor × season_factor

If NDVI > 0.7: yield ×= 1.2
If NDVI < 0.3: yield ×= 0.5
```

The latitude factor reduces yield by 3% per degree north of 55°N (e.g., at 62°N: `1 − 7 × 0.03 = 0.79`). The season factor scales linearly: a 100-day season gives 67% of the base.

### 4.4 Nutrient Assessment (`assess_overfertilization_risk`)

After WOFOST runs, each parcel also gets an N-budget assessment:

```
n_uptake     = yield_t_ha × N_UPTAKE_PER_TONNE[crop]
n_input      = user_value or auto_estimate(crop, yield)
n_surplus    = max(0, n_input − n_uptake)
runoff_risk  = f(runoff_score, total_rainfall)
leaching_risk = f(sand_frac, rainfall, n_surplus)
```

A composite overfertilization risk score (0–100) combines surplus amount, runoff×surplus interaction, leaching×surplus interaction, yield gap, heterogeneity, and satellite confidence.

---

## 5. Data Flow Diagram

```
User Query (lat, lon, date_range, municipality)
        │
        ▼
  ┌─────────────────┐
  │  fetch_weather   │─── Open-Meteo API (or fallback)
  │  (lat, lon,      │    ↓
  │   start, end)    │    DataFrame: DAY, IRRAD, TMIN, TMAX, VAP, RAIN, WIND, ET0
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  fetch_soil      │─── SoilGrids REST API (or fallback)
  │  (lat, lon)      │    ↓
  └────────┬────────┘    dict: clay, sand, silt, smw, smfc, s0, AWC, etc.
           │
           ▼
  ┌──────────────────────────────────┐
  │  _prepare_wofost_bundle          │  ← called ONCE
  │  ├─ detect_model_class()         │
  │  ├─ YAMLCropDataProvider()       │── crop YAML files (23 crops)
  │  ├─ _build_weather_provider()    │── WeatherDataContainer list
  │  └─ soil_params dict             │
  └──────────────┬───────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────┐
  │  ThreadPoolExecutor(max_workers=8)│
  │                                  │
  │  For each parcel:                │
  │  ┌────────────────────────────┐  │
  │  │ run_single_wofost()        │  │
  │  │ 1. CropResolver(label)     │──│── LPIS label → crop + variety
  │  │ 2. YAMLCropDataProvider()  │  │  (thread-local, from pickle cache)
  │  │ 3. set_active_crop()       │  │
  │  │ 4. ParameterProvider()     │──│── site + soil + crop data
  │  │ 5. Model() + run_till()    │──│── daily simulation
  │  │ 6. Extract yield/biomass   │  │
  │  │ 7. assess_overfertilization│  │── N surplus + risk score
  │  └────────────────────────────┘  │
  └──────────────┬───────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────┐
  │  _enrich_risks_with_wofost()     │
  │  ├─ wofost_yield_kg_ha           │
  │  ├─ wofost_total_yield_kg        │── yield × area_ha
  │  ├─ nutrient_n_surplus_kg_ha     │
  │  └─ nutrient_risk_score          │
  └──────────────┬───────────────────┘
                 │
                 ▼
          Streamlit Dashboard
```

---

## 6. Parameters at a Glance

### Weather inputs to WOFOST

| PCSE field | Meaning | Source | Unit |
|------------|---------|--------|------|
| IRRAD | Shortwave radiation | Open-Meteo × 100 | J/cm²/day |
| TMIN | Minimum temperature | Open-Meteo | °C |
| TMAX | Maximum temperature | Open-Meteo | °C |
| TEMP | Mean temperature | Open-Meteo | °C |
| VAP | Actual vapour pressure | Derived from T + RH | kPa |
| WIND | Max wind speed | Open-Meteo | m/s |
| RAIN | Precipitation | Open-Meteo | mm/day |
| E0 | Potential evaporation | PCSE reference_ET() | mm/day |
| ES0 | Potential soil evaporation | PCSE reference_ET() | mm/day |
| ET0 | Reference evapotranspiration | Open-Meteo alt. | mm/day |

### Soil inputs to WOFOST

| PCSE field | Meaning | From SoilGrids | Range |
|------------|---------|----------------|-------|
| SMW | Wilting point soil moisture | Clay % → empirical | 0.04–0.20 |
| SMFCF | Field capacity soil moisture | Clay % → empirical | 0.18–0.40 |
| SM0 | Saturation soil moisture | Clay % → empirical | 0.35–0.45 |
| CRAIRC | Critical air content | Fixed at 0.05 | 0.05 |
| SOPE | Max percolation rate | Fixed at 10 | cm/day |
| KSUB | Max capillary rise | Fixed at 1.0 | mm/day |
| WAV | Available water profile | AWC × root depth | mm |
| K0 | Hydraulic conductivity | Fixed at 0.01 | 1/day |

### Key crop parameters

| Parameter | Meaning | Impact | Typically calibrated? |
|-----------|---------|--------|----------------------|
| TSUM1 | Thermal sum to anthesis | Determines timing of grain fill | Must recalibrate per region |
| TSUM2 | Thermal sum to maturity | Determines if grain fill completes | Must recalibrate per region |
| AMAXTB | Max leaf CO₂ assimilation | Drives potential yield | Defaults from WOFOST72 |
| FRTB/FLTB/FSTB/FOTB | Partitioning fractions | Dry matter to leaf/stem/root/storage | Standard defaults |
| KDIFF | Extinction coefficient | Light interception efficiency | ~0.6 for cereals |
| CVL/CVO/CVR/CVS | Conversion efficiencies | Assimilate → dry matter | Standard defaults |
| TDWI | Initial total dry weight | Emergence biomass | 10–30 kg/ha |

---

## 7. Known Limitations & Calibration Needs

1. **TSUM1/TSUM2 Dutch-calibrated**: Default values assume warm continental climate. For Swedish conditions at 62°N, the temperature sum is insufficient — WOFOST never reaches DVS=2 and yields 0. Fix: adjust TSUM1 from ~1250 to ~850 and TSUM2 from ~750 to ~550 for spring cereals.

2. **Soil water from clay % only**: A three-class lookup table is a crude approximation. Real soil hydraulic properties depend on structure, organic matter, compaction, and horizon sequences. Using the full Van Genuchten-Mualem parameters would improve water-stress simulation.

3. **Single soil profile per query**: SoilGrids values at the center lat/lon represent the entire area. For municipality-scale queries (30+ km across), soil variability is substantial. Per-parcel SoilGrids queries or the Swedish "Markinfo" dataset would improve accuracy.

4. **No N-limited mode**: `Wofost72_WLP_FD` simulates water limitation only. `Wofost80_NWLP_FD_beta` adds nitrogen limitation but may not be available in the installed PCSE version. Without NWLP, the nutrient assessment is post-hoc (separate from the crop model).

5. **Flat elevation**: All parcels are assumed at 50 m elevation. Topography affects temperature, radiation, and precipitation, but Gödslingskollen uses a single weather fetch for the entire area.

6. **Single crop per parcel**: WOFOST simulates a mono-culture. Intercropping, undersown catch crops, and relay cropping are not modeled.

7. **Spin-up not performed**: The water balance starts from default moisture (SM0/2). For accurate simulation, a spin-up year is typically needed to initialize soil moisture realistically.
