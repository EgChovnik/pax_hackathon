"""
features.py — ЕДИНСТВЕННОЕ место, где считаются признаки.

Главное правило: и train.py, и predict.py вызывают build_features().
Если признаки на обучении и инференсе считаются одним кодом —
исчезает главный источник багов «на трейне было иначе».

Вход: длинный DataFrame факта/каркаса (route_id, stop_id, ts_start [, pax_in])
    + справочники внешних данных.
Выход: тот же DataFrame + колонки-признаки. Список признаков — в FEATURES.
"""

import pandas as pd

# Финальный список признаков, который идёт в модель.
# Дополняйте по мере добавления — train и predict берут его отсюда.
FEATURES = [
    # время
    "hour", "dow", "is_weekend", "month",
    # календарь (ingest/calendar_ru.py)
    "is_holiday", "day_before_holiday", "day_after_holiday", "is_school_break",
    # лаги и скользящие (только на истории!)
    "lag_1h", "lag_1d", "lag_1w", "rolling_mean_3h",
    # погода (ingest/weather.py)
    "temp", "precip_mm", "is_rain", "is_snow",
    # трафик (ingest/traffic.py)
    "congestion",
    # события (ingest/events.py)
    "event_nearby",
    # география
    "stop_seq",          # позиция остановки на маршруте
    "route_id",          # категориальный, CatBoost съест как есть
]

CAT_FEATURES = ["route_id", "dow", "hour", "month"]


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    ts = df["ts_start"]
    df["hour"] = ts.dt.hour
    df["dow"] = ts.dt.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["month"] = ts.dt.month
    return df


def add_lags(df: pd.DataFrame, target: str = "pax_in") -> pd.DataFrame:
    """Лаги по каждой точке (route_id, stop_id). Требуют истории.

    ВАЖНО про инференс: на горизонте «день вперёд» lag_1h недоступен.
    Решение для хакатона: использовать только лаги >= горизонта
    (lag_1d, lag_1w) либо подставлять последнее известное значение.
    """
    g = df.sort_values("ts_start").groupby(["route_id", "stop_id"])[target]
    df["lag_1h"] = g.shift(1)          # TODO: подстроить под ваш interval
    df["lag_1d"] = g.shift(24)
    df["lag_1w"] = g.shift(24 * 7)
    df["rolling_mean_3h"] = g.shift(1).rolling(3).mean().reset_index(drop=True)
    return df


def merge_externals(df, weather=None, calendar=None, traffic=None, events=None):
    """Присоединить внешние источники. Каждый — отдельный merge, чтобы
    ablation (обучение «без фактора») делался простым отключением merge."""
    if calendar is not None:
        df = df.merge(calendar, left_on=df["ts_start"].dt.date.astype("string"),
                      right_on="date", how="left")
    if weather is not None:  # по часу
        df["ts_hour"] = df["ts_start"].dt.floor("h")
        df = df.merge(weather, left_on="ts_hour", right_on="ts", how="left")
    if traffic is not None:  # исторический паттерн: (dow, hour) -> congestion
        df = df.merge(traffic, on=["dow", "hour"], how="left")
    if events is not None:
        # TODO: event_nearby = есть событие в радиусе R км в окне ±2ч
        df["event_nearby"] = 0
    return df


def build_features(df, weather=None, calendar=None, traffic=None,
                   events=None, dropna_lags: bool = True) -> pd.DataFrame:
    """Полный пайплайн признаков. dropna_lags=True на обучении
    (первая неделя без лагов выбрасывается), False на инференсе."""
    df = add_time_features(df)
    df = merge_externals(df, weather, calendar, traffic, events)
    if "pax_in" in df.columns:
        df = add_lags(df)
    if dropna_lags:
        df = df.dropna(subset=["lag_1w"])
    # заполнить пропуски внешних данных нейтральными значениями
    df = df.fillna({"temp": df.get("temp", pd.Series()).median(),
                    "precip_mm": 0, "is_rain": 0, "is_snow": 0,
                    "congestion": 5, "event_nearby": 0})
    return df
