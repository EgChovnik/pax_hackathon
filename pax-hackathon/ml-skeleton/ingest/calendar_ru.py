"""
ingest/calendar_ru.py — производственный календарь РФ + каникулы.

Источник: isdayoff.ru — простой GET, без ключа.
  https://isdayoff.ru/api/getdata?year=2026  -> строка из 0/1 по дням года
Каникулы Москвы: даты из приказов ДОНМ, за 2 дня хакатона проще
захардкодить список периодов и дать ссылку на приказ в README.

Выход: DataFrame [date, is_holiday, day_before_holiday, day_after_holiday,
                  is_school_break, day_type, source_url]
"""

import pandas as pd
import requests

SOURCE_URL = "https://isdayoff.ru/"

# TODO: актуализировать под ваш период данных, ссылку на приказ — в README
SCHOOL_BREAKS = [
    ("2025-10-25", "2025-11-04"),
    ("2025-12-31", "2026-01-11"),
    ("2026-03-21", "2026-03-29"),
    ("2026-06-01", "2026-08-31"),
]


def fetch_year(year: int) -> pd.DataFrame:
    r = requests.get("https://isdayoff.ru/api/getdata",
                     params={"year": year}, timeout=30)
    r.raise_for_status()
    days = [int(c) for c in r.text.strip()]
    dates = pd.date_range(f"{year}-01-01", periods=len(days))
    df = pd.DataFrame({"date": dates, "is_holiday": days})

    # «хвосты» праздников: поток меняется и накануне, и после
    df["day_before_holiday"] = df["is_holiday"].shift(-1).fillna(0).astype(int)
    df["day_after_holiday"] = df["is_holiday"].shift(1).fillna(0).astype(int)

    df["is_school_break"] = 0
    for a, b in SCHOOL_BREAKS:
        df.loc[df["date"].between(a, b), "is_school_break"] = 1

    df["day_type"] = df.apply(
        lambda r: "holiday" if r.is_holiday
        else ("weekend" if r.date.dayofweek >= 5 else "workday"), axis=1)
    df["source_url"] = SOURCE_URL
    df["date"] = df["date"].dt.date.astype("string")
    return df


if __name__ == "__main__":
    df = pd.concat([fetch_year(2025), fetch_year(2026)])
    df.to_parquet("data/calendar.parquet", index=False)
    print(df.head(10))
