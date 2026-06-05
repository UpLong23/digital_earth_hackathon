import json, os, time
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

import numpy as np
import pandas as pd

from backend.cache import cache_get, cache_set

WEATHER_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "weather"
WEATHER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_PARAMS = [
    "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
    "precipitation_sum", "shortwave_radiation_sum",
    "et0_fao_evapotranspiration", "wind_speed_10m_max",
    "relative_humidity_2m_mean",
]


def _round_coord(v, digits=1):
    return round(v, digits)


def _cache_key(lat, lon, start, end):
    return f"weather_{_round_coord(lat)}_{_round_coord(lon)}_{start}_{end}"


def _build_url(lat, lon, start, end):
    is_forecast = (date.today() - date.fromisoformat(str(start))).days < 5
    base = FORECAST_URL if is_forecast else ARCHIVE_URL
    params = ",".join(DAILY_PARAMS)
    return (
        f"{base}?latitude={lat}&longitude={lon}"
        f"&daily={params}&timezone=auto"
        f"&start_date={start}&end_date={end}"
    )


def _vapour_pressure(tmean_c, rh_mean):
    """Actual vapour pressure (kPa) from temperature and relative humidity."""
    es = 0.6108 * np.exp((17.27 * tmean_c) / (tmean_c + 237.3))
    return es * (rh_mean / 100.0)


def _to_pcse_weather(df: pd.DataFrame) -> pd.DataFrame:
    """Convert Open-Meteo daily DataFrame to PCSE-compatible weather table."""
    out = pd.DataFrame()
    out["DAY"] = pd.to_datetime(df["time"])
    # IRRAD: shortwave radiation sum J/cm2/day (Open-Meteo gives MJ/m2, convert: *100)
    out["IRRAD"] = df["shortwave_radiation_sum"].fillna(0) * 100.0
    out["TMIN"] = df["temperature_2m_min"].fillna(0)
    out["TMAX"] = df["temperature_2m_max"].fillna(0)
    out["TEMP"] = df["temperature_2m_mean"].fillna((out["TMIN"] + out["TMAX"]) / 2)
    rh = df["relative_humidity_2m_mean"].fillna(70)
    out["VAP"] = _vapour_pressure(out["TEMP"], rh)
    out["WIND"] = df["wind_speed_10m_max"].fillna(2.0)
    out["RAIN"] = df["precipitation_sum"].fillna(0)
    out["ET0"] = df["et0_fao_evapotranspiration"].fillna(0)
    return out


def fetch_weather(lat: float, lon: float,
                  start_date, end_date,
                  retries=2) -> pd.DataFrame:
    """Fetch daily weather from Open-Meteo, return PCSE-formatted DataFrame.

    Falls back to synthetic typical Swedish weather on failure.
    """
    start = start_date if isinstance(start_date, str) else start_date.isoformat()
    end = end_date if isinstance(end_date, str) else end_date.isoformat()
    ck = _cache_key(lat, lon, start, end)

    cached = cache_get(ck, ttl_seconds=3600)
    if cached is not None:
        df = pd.DataFrame(cached)
        df["DAY"] = pd.to_datetime(df["DAY"])
        return df

    url = _build_url(lat, lon, start, end)
    for attempt in range(retries + 1):
        try:
            resp = json.loads(urlopen(url, timeout=15).read())
            daily = resp.get("daily", {})
            if "time" not in daily:
                raise ValueError("No daily data in response")
            df = pd.DataFrame(daily)
            pcse_df = _to_pcse_weather(df)
            cache_set(ck, pcse_df.to_dict(orient="list"))
            return pcse_df
        except Exception as exc:
            if attempt < retries:
                time.sleep(2)
                continue
            # Fallback: typical Swedish summer weather
            return _fallback_weather(start, end)


def _fallback_weather(start, end):
    """Generate synthetic typical Swedish growing-season weather."""
    start = date.fromisoformat(str(start)) if isinstance(start, str) else start
    end = date.fromisoformat(str(end)) if isinstance(end, str) else end
    days = (end - start).days or 120
    dates = [start + timedelta(days=i) for i in range(days)]
    n = len(dates)
    rng = np.random.default_rng(42)
    tmean = 14 + 6 * np.sin(np.linspace(0, np.pi, n)) + rng.normal(0, 2, n)
    tmin = tmean - 4 + rng.normal(0, 1, n)
    tmax = tmean + 4 + rng.normal(0, 1, n)
    rain = np.maximum(0, rng.exponential(3, n))
    rad = 12 + 6 * np.sin(np.linspace(0, np.pi, n)) + rng.normal(0, 2, n)
    et0 = 2.5 + 1.5 * np.sin(np.linspace(0, np.pi, n)) + rng.normal(0, 0.5, n)
    wind = rng.uniform(2, 6, n)
    rh = rng.uniform(60, 85, n)

    df = pd.DataFrame({
        "DAY": dates,
        "IRRAD": np.maximum(rad * 100, 100),
        "TMIN": tmin,
        "TMAX": tmax,
        "TEMP": tmean,
        "VAP": [_vapour_pressure(t, rh[i]) for i, t in enumerate(tmean)],
        "WIND": wind,
        "RAIN": rain,
        "ET0": et0,
    })
    return df
