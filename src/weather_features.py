"""出没記録に日付由来の季節属性と任意の気象属性を付与する。

気象データは data/weather_daily.csv があれば結合する。CSV は最低限
date 列を持ち、必要に応じて temp_avg, precipitation, weather などの列を
追加できる。station 列がある場合は記録に最も近い地点の値を採用する。
"""
from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt

import numpy as np
import pandas as pd

import config as C

SEASON_LABELS = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "winter": "冬",
}

ACTIVITY_LABELS = {
    "post_hibernation": "冬眠明け・春の移動期",
    "breeding": "繁殖期・行動圏拡大期",
    "hyperphagia": "秋の採食集中期",
    "denning": "冬眠期・低活動期",
}

WEATHER_COLUMNS = [
    "station",
    "station_lat",
    "station_lon",
    "weather",
    "temp_avg",
    "temp_max",
    "temp_min",
    "precipitation",
    "snowfall",
    "sunshine",
    "wind_speed",
]


def _season(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _activity_period(month: int) -> str:
    if month in (3, 4, 5):
        return "post_hibernation"
    if month in (6, 7, 8):
        return "breeding"
    if month in (9, 10, 11):
        return "hyperphagia"
    return "denning"


def _moon_phase_index(date: pd.Timestamp) -> float:
    """簡易的な月齢指数を 0-1 で返す（0/1: 新月付近, 0.5: 満月付近）。"""
    known_new_moon = pd.Timestamp("2000-01-06")
    synodic_month = 29.53058867
    days = (date.normalize() - known_new_moon).days
    return float((days % synodic_month) / synodic_month)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = radians(lat1)
    p2 = radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _load_weather() -> pd.DataFrame:
    if not C.WEATHER_DAILY_CSV.exists():
        return pd.DataFrame()

    weather = pd.read_csv(C.WEATHER_DAILY_CSV)
    if "date" not in weather.columns:
        raise ValueError(f"{C.WEATHER_DAILY_CSV} に date 列が必要です")
    weather["date"] = pd.to_datetime(weather["date"], errors="coerce")
    weather = weather.dropna(subset=["date"])
    return weather


def _merge_weather_by_date(sightings: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    available = [c for c in WEATHER_COLUMNS if c in weather.columns]
    if not available:
        return sightings

    if {"station_lat", "station_lon"}.issubset(weather.columns):
        rows = []
        for _, sighting in sightings.iterrows():
            candidates = weather[weather["date"] == sighting["date"]]
            if candidates.empty:
                rows.append({c: np.nan for c in available})
                continue
            distances = candidates.apply(
                lambda r: _haversine_km(
                    sighting["lat"], sighting["lon"], r["station_lat"], r["station_lon"]
                ),
                axis=1,
            )
            nearest = candidates.loc[distances.idxmin(), available].to_dict()
            nearest["weather_station_distance_km"] = round(float(distances.min()), 2)
            rows.append(nearest)
        return pd.concat([sightings.reset_index(drop=True), pd.DataFrame(rows)], axis=1)

    weather_by_date = weather[["date", *available]].drop_duplicates("date")
    return sightings.merge(weather_by_date, on="date", how="left")


def enrich_sightings(sightings: pd.DataFrame) -> pd.DataFrame:
    """出没記録に季節・月・任意の気象データを付与する。"""
    out = sightings.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    out["day_of_year"] = out["date"].dt.dayofyear
    out["season"] = out["month"].apply(lambda m: _season(int(m)) if pd.notna(m) else None)
    out["season_label"] = out["season"].map(SEASON_LABELS)
    out["activity_period"] = out["month"].apply(
        lambda m: _activity_period(int(m)) if pd.notna(m) else None
    )
    out["activity_period_label"] = out["activity_period"].map(ACTIVITY_LABELS)
    out["is_food_season"] = out["month"].isin([9, 10, 11])
    out["is_denning_season"] = out["month"].isin([12, 1, 2])
    out["moon_phase"] = out["date"].apply(
        lambda d: round(_moon_phase_index(d), 3) if pd.notna(d) else np.nan
    )

    weather = _load_weather()
    if not weather.empty:
        out = _merge_weather_by_date(out, weather)

    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out
