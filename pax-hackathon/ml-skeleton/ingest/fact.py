"""
ingest/fact.py — агрегация сырых логов валидаций в таблицу факта для ML.

Вход (типичный лог, 1 строка = 1 событие входа пассажира):
    ts, route_id, stop_id [, card_id, vehicle_id, direction]
Выход: data/fact.parquet, длинный формат:
    route_id, stop_id, ts_start, interval, pax_in, pax_out

Порядок обработки (каждый шаг — отдельная функция, легко тестировать):
    load -> clean -> dedup -> aggregate -> fill_zero_intervals -> drop_bad_days
"""

import pandas as pd

INTERVAL = "1h"          # базовая гранулярность; более крупные — агрегацией
TZ_NOTE = "все ts приводим к МСК и делаем naive — одинаково во всём проекте"


def load_raw(path: str) -> pd.DataFrame:
    """TODO: подстроить под формат организаторов (csv/parquet, имена колонок).
    Обязательно привести:
      - ts -> datetime, к МСК, tz-naive
      - route_id, stop_id -> string (иначе '007' превратится в 7)
    """
    df = pd.read_csv(path, dtype={"route_id": "string", "stop_id": "string"})
    df["ts"] = pd.to_datetime(df["ts"])
    # если ts в UTC: df["ts"] = df["ts"].dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Мусор: пустые ключи, время вне периода данных, несуществующие остановки."""
    df = df.dropna(subset=["ts", "route_id", "stop_id"])
    stops = pd.read_parquet("data/route_stops.parquet")
    valid = set(zip(stops["route_id"], stops["stop_id"]))
    mask = list(zip(df["route_id"], df["stop_id"]))
    df = df[pd.Series(mask, index=df.index).isin(valid)]
    return df


def dedup(df: pd.DataFrame, window: str = "2min") -> pd.DataFrame:
    """Схлопнуть повторные прикладывания той же карты на той же остановке
    в пределах window. Если card_id нет — пропустить шаг."""
    if "card_id" not in df.columns:
        return df
    df = df.sort_values("ts")
    prev = df.groupby(["card_id", "stop_id"])["ts"].shift(1)
    return df[(df["ts"] - prev).isna() | ((df["ts"] - prev) > pd.Timedelta(window))]


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Событие -> интервал. Полуоткрытые интервалы [start, start+INTERVAL)."""
    df["ts_start"] = df["ts"].dt.floor(INTERVAL)
    out = (df.groupby(["route_id", "stop_id", "ts_start"])
             .size().rename("pax_in").reset_index())
    return out


def fill_zero_intervals(fact: pd.DataFrame) -> pd.DataFrame:
    """КРИТИЧНО: достроить полную сетку точка x интервал и заполнить нулями.
    Интервал без событий = 0 пассажиров, а не отсутствующая строка.
    Без этого модель обучится только на «ненулевых» примерах и будет
    завышать прогноз ночью и на тихих остановках."""
    points = fact[["route_id", "stop_id"]].drop_duplicates()
    ts = pd.date_range(fact["ts_start"].min(), fact["ts_start"].max(),
                       freq=INTERVAL)
    grid = points.merge(pd.DataFrame({"ts_start": ts}), how="cross")
    fact = grid.merge(fact, on=["route_id", "stop_id", "ts_start"], how="left")
    fact["pax_in"] = fact["pax_in"].fillna(0)
    return fact


def drop_bad_days(fact: pd.DataFrame, thresh: float = 0.1) -> pd.DataFrame:
    """Дни-поломки сборщика: суммарный поток дня < thresh * медианы по
    тому же дню недели -> исключить из обучения ЦЕЛИКОМ. Это «нет данных»,
    а не «не было пассажиров» — путать нельзя.
    Список выброшенных дней логируем — пригодится для README."""
    daily = fact.groupby(fact["ts_start"].dt.date)["pax_in"].sum()
    dow = pd.Series(pd.to_datetime(daily.index).dayofweek, index=daily.index)
    med = daily.groupby(dow).transform("median")
    bad = daily[daily < thresh * med].index
    if len(bad):
        print(f"Исключены дни (сбой данных): {sorted(bad)}")
    return fact[~fact["ts_start"].dt.date.isin(bad)]


def add_pax_out(fact: pd.DataFrame) -> pd.DataFrame:
    """В логах валидаций обычно есть только вход. Варианты по возрастанию
    сложности (выбранный подход честно описать в README):
    1) Зеркало: выход на остановке ~ вход на ней же в обратном направлении
       с лагом времени поездки.
    2) Исторические доли высадки по позиции остановки (конец маршрута
       собирает больше выходов).
    TODO: реализовать вариант 2 как дефолт."""
    fact["pax_out"] = fact["pax_in"]  # заглушка, чтобы пайплайн работал
    return fact


def main(path_raw: str = "data/raw_logs.csv"):
    df = load_raw(path_raw)
    n0 = len(df)
    df = clean(df)
    df = dedup(df)
    fact = aggregate(df)
    fact = fill_zero_intervals(fact)
    fact = drop_bad_days(fact)
    fact = add_pax_out(fact)
    fact["interval"] = INTERVAL

    # sanity-отчёт: эти числа должны сходиться с ожиданиями
    print(f"событий: {n0} -> после чистки: {len(df)}")
    print(f"строк факта: {len(fact)}, доля нулевых: "
          f"{(fact['pax_in'] == 0).mean():.1%}")
    print(f"период: {fact['ts_start'].min()} .. {fact['ts_start'].max()}")

    fact.to_parquet("data/fact.parquet", index=False)


if __name__ == "__main__":
    main()
