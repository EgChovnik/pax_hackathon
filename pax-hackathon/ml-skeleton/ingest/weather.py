"""
ingest/weather.py — погода: архив для обучения + прогноз для инференса.

Источник: Open-Meteo, без API-ключа.
  Архив:   https://archive-api.open-meteo.com/v1/archive
  Прогноз: https://api.open-meteo.com/v1/forecast
SOURCE_URL обязателен — за источник без ссылки балл не дают.

Выход: DataFrame [ts, temp, precip_mm, is_rain, is_snow, source_url]
по часам, Москва (55.75, 37.62). Сохранять в data/weather.parquet.
"""

import pandas as pd
import requests

SOURCE_URL = "https://open-meteo.com/"
LAT, LON = 55.75, 37.62
HOURLY = "temperature_2m,precipitation,rain,snowfall"


def _to_df(js: dict) -> pd.DataFrame:
    h = js["hourly"]
    df = pd.DataFrame({
        "ts": pd.to_datetime(h["time"]),
        "temp": h["temperature_2m"],
        "precip_mm": h["precipitation"],
        "is_rain": [int(x > 0.1) for x in h["rain"]],
        "is_snow": [int(x > 0.1) for x in h["snowfall"]],
    })
    df["source_url"] = SOURCE_URL
    return df


def fetch_history(date_from: str, date_to: str) -> pd.DataFrame:
    """Архив погоды за период обучения. Даты в формате YYYY-MM-DD."""
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={"latitude": LAT, "longitude": LON,
                "start_date": date_from, "end_date": date_to,
                "hourly": HOURLY, "timezone": "Europe/Moscow"},
        timeout=30,
    )
    r.raise_for_status()
    return _to_df(r.json())


def fetch_forecast(days: int = 7) -> pd.DataFrame:
    """Прогноз погоды — нужен для инференса на будущие даты."""
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": LAT, "longitude": LON,
                "forecast_days": days,
                "hourly": HOURLY, "timezone": "Europe/Moscow"},
        timeout=30,
    )
    r.raise_for_status()
    return _to_df(r.json())


if __name__ == "__main__":
    df = fetch_history("2025-01-01", "2025-01-07")
    df.to_parquet("data/weather.parquet", index=False)
    print(df.head())
