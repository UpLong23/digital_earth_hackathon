# 3-Minute Live Demo Script — Gödslingskollen

**Setup**: App running at `localhost:8501`, Lund municipality selected, demo mode ON, WOFOST OFF. Maximise browser window.

---

### 0:00 – 0:20  |  Hook & Problem

> "Swedish farmers apply ~100 kg N/ha on average. But without field-level feedback, excess nitrogen leaks into the Baltic — costing farmers money and damaging the environment. Gödslingskollen detects which fields are likely overfertilized, using free satellite data and crop modeling."

*(Click nothing yet. Point at the screen.)*

---

### 0:20 – 0:40  |  Load Lund

> "We've preloaded Lund municipality — 1,200 real LPIS parcels from Jordbruksverket. Each colour is a risk score: green = low, yellow = moderate, orange = high, red = critical."

*(Hover mouse over the legend in the sidebar.)*

> "Sidebar shows all controls: municipality picker, date range, crop filter. Demo mode is ON so this runs instantly without satellite credentials."

---

### 0:40 – 1:10  |  Map Interaction

> "Let's click a red parcel."

*(Click a high-risk red/orange polygon. Popup appears.)*

> "Popup shows: parcel ID, crop type, NDVI, NDRE, vigour z-score (how abnormal this field is vs its peers), heterogeneity, and confidence. This field has NDVI 0.82 — very green — and a vigour z of +3.1, meaning it's three standard deviations above the average barley field in Lund. That's suspicious."

*(Pan around casually.)*

> "Layer control lets you toggle between the light map and satellite imagery. The municipality boundary switches colour automatically."

*(Toggle to satellite, then back.)*

---

### 1:10 – 1:35  |  Summary Cards & Top Risks

> "Below the map: five summary cards. Average risk 34/100 — moderate overall. 12 parcels are critical. On the left, top 5 highest-risk parcels. On the right, crop distribution — mostly spring barley and winter wheat, typical for Skåne."

*(Briefly point at each element.)*

---

### 1:35 – 1:55  |  Time Series & Data

> "Time series shows NDVI over the season for the highest- and lowest-risk parcels plus random samples. The high-risk line stays elevated — consistently greener than peers. The third row is the risk histogram: a long tail to the right."

*(Scroll down slightly.)*

> "Expand the data table — every single parcel with all metrics, downloadable as CSV. WOFOST fields appear here when the model is enabled."

*(Click the expander briefly.)*

---

### 1:55 – 2:30  |  WOFOST Toggle (Optional)

> "Now the interesting part. Let's enable WOFOST."

*(Toggle ON "Enable WOFOST crop modeling" — note: needs real/connected mode actually; in demo mode it uses heuristic estimates. Adapt for your setup.)*

> "WOFOST simulates daily crop growth for each parcel — weather-driven, soil-aware. It estimates yield and biomass. Then the nutrient module computes N surplus = applied N minus crop uptake. The dashboard now shows yield per crop type and per parcel, plus WOFOST summary metrics."

*(Point at the yield bar charts.)*

> "This is where SoilGrids feeds in — clay content determines field capacity, which affects water stress, which affects yield, which affects the N surplus estimate."

---

### 2:30 – 2:50  |  Live Satellite (If Available)

> "If we had real Copernicus credentials, we'd click **Connect** → authenticate via OIDC → **Fetch real satellite data**. That downloads actual Sentinel-2 NDVI/NDRE + DEM, runs zonal statistics to extract per-field values, and replaces the synthetic scores with real satellite observations. It takes about 3 minutes for a municipality."

---

### 2:50 – 3:00  |  Close

> "Summary: we take free open data — LPIS parcels, Sentinel-2, EU-DEM, Open-Meteo, SoilGrids — and combine them with WOFOST crop modeling into a single risk score per field. Built for the Digital Earth Sweden Hackathon. Questions?"

---

## Tips

- **Pre-cache everything** before presenting (run through the full Lund load once).
- **Have the terminal ready** to restart if needed: `uv run streamlit run main.py`
- **If WOFOST takes too long**, skip it or have it pre-loaded. Demo mode heuristic is instant.
- **Know your Lund geography**: point out Öresund, the university, etc. to connect with the audience.
- **If the map lags with 1,200 parcels**, blame Leaflet rendering limits (not the app).
