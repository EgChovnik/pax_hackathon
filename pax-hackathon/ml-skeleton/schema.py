"""
schema.py — КОНТРАКТ между ML и бэкендом. Фиксируется в день 1 и не меняется.

Идея: любой DataFrame с прогнозом проходит через validate() перед записью
в parquet. Если ML что-то сломает — упадёт сразу у ML, а не тихо у бэкенда.
"""

import pandas as pd

# Схема forecast.parquet: одна строка = прогноз для точки в один интервал
FORECAST_COLUMNS = {
    "route_id": "string",
    "stop_id": "string",
    "segment_id": "string",        # nullable, для участков
    "ts_start": "datetime64[ns]",  # ЕДИНАЯ таймзона везде (МСК naive)
    "interval": "string",          # "15min" | "1h" | "1d"
    "horizon": "string",           # "day" | "month" | "year"
    "pax_in": "float64",
    "pax_out": "float64",
    "load_pct": "float64",         # 1.15 = 115% заполненности
    "pred_low": "float64",         # квантиль 0.1
    "pred_high": "float64",        # квантиль 0.9
    "in_domain": "bool",           # в области обучения?
    "model_version": "string",
}

HORIZONS = ["day", "month", "year"]


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Проверить и привести DataFrame к контракту. Бросает ValueError."""
    missing = set(FORECAST_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Нет колонок: {missing}")

    df = df[list(FORECAST_COLUMNS)].astype(FORECAST_COLUMNS)

    if not df["horizon"].isin(HORIZONS).all():
        raise ValueError("horizon вне списка HORIZONS")
    if (df["pax_in"] < 0).any() or (df["pax_out"] < 0).any():
        raise ValueError("Отрицательный пассажиропоток")
    if (df["pred_low"] > df["pred_high"]).any():
        raise ValueError("pred_low > pred_high")

    return df


def write_forecast(df: pd.DataFrame, path: str = "data/forecast") -> None:
    """Атомарная запись: сначала во временную папку, потом переименование.

    Партиционируем по horizon — бэкенд читает только нужный кусок.
    """
    df = validate(df)
    df.to_parquet(path, partition_cols=["horizon"], index=False)
