"""
ml/predict.py — ЕДИНСТВЕННАЯ точка входа для бэкенда.

Бэкенд не знает про признаки и CatBoost — он вызывает predict()
и получает DataFrame по контракту schema.FORECAST_COLUMNS.
Внутри: каркас будущих интервалов -> внешние данные -> признаки -> модель.
"""

import json
from pathlib import Path

import pandas as pd
from catboost import CatBoostRegressor

from features import build_features, FEATURES
from ingest.weather import fetch_forecast
from schema import validate

MODEL_DIR = Path("models/v1")
_cache = {}


def _load():
    if not _cache:
        for name in ("model", "model_q10", "model_q90"):
            m = CatBoostRegressor()
            m.load_model(MODEL_DIR / f"{name}.cbm")
            _cache[name] = m
        _cache["meta"] = json.loads((MODEL_DIR / "meta.json").read_text())
    return _cache


def _in_domain(df, meta) -> pd.Series:
    """Флаг области применимости из meta.json (критерий 2б)."""
    ok_route = df["route_id"].isin(meta["domain"]["routes"])
    t = meta["domain"]["feature_ranges"]["temp"]
    ok_temp = df["temp"].between(t[0] - 5, t[1] + 5)
    return ok_route & ok_temp


def predict(route_ids: list[str], ts_from: str, ts_to: str,
            interval: str = "1h", horizon: str = "day") -> pd.DataFrame:
    c = _load()
    meta = c["meta"]

    # 1. каркас: точки x будущие интервалы
    stops = pd.read_parquet("data/route_stops.parquet")  # route_id, stop_id, seq
    stops = stops[stops["route_id"].isin(route_ids)]
    ts = pd.date_range(ts_from, ts_to, freq=interval)
    grid = stops.merge(pd.DataFrame({"ts_start": ts}), how="cross")
    grid = grid.rename(columns={"seq": "stop_seq"})

    # 2. внешние данные на будущее + история для лагов
    weather = fetch_forecast(days=8)
    calendar = pd.read_parquet("data/calendar.parquet")
    traffic = pd.read_parquet("data/traffic.parquet")
    hist = pd.read_parquet("data/fact.parquet")  # для лагов lag_1d / lag_1w
    frame = pd.concat([hist, grid], ignore_index=True)

    X = build_features(frame, weather=weather, calendar=calendar,
                       traffic=traffic, dropna_lags=False)
    X = X[X["ts_start"].isin(ts)]  # оставить только будущее

    # 3. прогноз
    out = grid.copy()
    out["pax_in"] = c["model"].predict(X[FEATURES]).clip(min=0)
    out["pred_low"] = c["model_q10"].predict(X[FEATURES]).clip(min=0)
    out["pred_high"] = c["model_q90"].predict(X[FEATURES]).clip(min=0)
    out["pax_out"] = out["pax_in"]  # TODO: вторая модель на pax_out

    # 4. load_pct: кумулятивная посадка/высадка вдоль маршрута / вместимость
    out = out.sort_values(["route_id", "ts_start", "stop_seq"])
    onboard = (out.groupby(["route_id", "ts_start"])
               .apply(lambda g: (g["pax_in"] - g["pax_out"]).cumsum())
               .reset_index(drop=True))
    capacity = 90  # TODO: из vehicles.parquet по маршруту
    out["load_pct"] = (onboard.values / capacity).clip(min=0)

    out["segment_id"] = pd.NA
    out["interval"] = interval
    out["horizon"] = horizon
    out["in_domain"] = _in_domain(X, meta).values
    out["model_version"] = meta["model_version"]
    return validate(out)
