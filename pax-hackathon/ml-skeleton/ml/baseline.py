"""
ml/baseline.py — seasonal naive: прогноз = то же время той же недели назад.

Зачем: это точка отсчёта. «Наша модель на X% точнее наивной» звучит
убедительнее любого абсолютного MAPE. Плюс это первый прогноз, который
уже в день 1 уходит бэкенду через forecast.parquet — интеграция начинается
сразу, а модель подменится позже без изменения контракта.
"""

import pandas as pd


def seasonal_naive(fact: pd.DataFrame, target_dates: pd.DatetimeIndex,
                   target: str = "pax_in") -> pd.DataFrame:
    """Для каждой (route_id, stop_id, час) будущей даты берём значение
    неделю назад из факта."""
    fact = fact.copy()
    fact["key_ts"] = fact["ts_start"] + pd.Timedelta(weeks=1)
    lookup = fact.set_index(["route_id", "stop_id", "key_ts"])[target]

    grid = (
        fact[["route_id", "stop_id"]].drop_duplicates()
        .merge(pd.DataFrame({"ts_start": target_dates}), how="cross")
    )
    grid["pred"] = lookup.reindex(
        pd.MultiIndex.from_frame(grid[["route_id", "stop_id", "ts_start"]])
    ).values
    # дыра в истории -> среднее по точке и часу
    fallback = fact.groupby(
        ["route_id", "stop_id", fact["ts_start"].dt.hour])[target].mean()
    grid["hour"] = grid["ts_start"].dt.hour
    idx = pd.MultiIndex.from_frame(grid[["route_id", "stop_id", "hour"]])
    grid["pred"] = grid["pred"].fillna(pd.Series(
        fallback.reindex(idx).values, index=grid.index))
    return grid.drop(columns="hour")


def mape(y_true, y_pred) -> float:
    m = y_true > 1  # не делим на около-нулевой поток
    return float((abs(y_true[m] - y_pred[m]) / y_true[m]).mean())
