"""
ml/batch_forecast.py — предрасчёт прогнозов. Запускается по `make forecast`
или ночным cron. Бэкенд читает готовый parquet и отвечает за миллисекунды —
это и есть цифры latency/RPS для README (критерий 3).

Горизонты месяц/год НЕ гоняются через ML-модель:
- месяц = средний дневной профиль x недельная сезонность x календарь;
- год = тренд + помесячная сезонность агрегата, разложить на остановки
  по историческим долям, пометить in_domain=False («качественная оценка»).
"""

import pandas as pd

from ml.predict import predict, _load
from schema import write_forecast, FORECAST_COLUMNS


def forecast_day(routes, days=7):
    start = pd.Timestamp.now().floor("D") + pd.Timedelta(days=1)
    return predict(routes,
                   ts_from=str(start),
                   ts_to=str(start + pd.Timedelta(days=days)),
                   interval="1h", horizon="day")


def forecast_month(fact, calendar):
    """Профильный подход: (route, stop, day_type, hour) -> средний поток,
    растянутый на дни следующего месяца по календарю."""
    prof = (fact.assign(hour=fact["ts_start"].dt.hour,
                        date=fact["ts_start"].dt.date.astype("string"))
            .merge(calendar[["date", "day_type"]], on="date")
            .groupby(["route_id", "stop_id", "day_type", "hour"])["pax_in"]
            .mean().reset_index())
    # TODO: cross с датами следующего месяца из calendar, собрать колонки
    # контракта (pred_low/high = +-20%, in_domain=True, horizon="month")
    raise NotImplementedError


def forecast_year(fact):
    """Тренд + месячная сезонность по агрегату маршрута; доли остановок —
    исторические. horizon='year', in_domain=False."""
    raise NotImplementedError


def main():
    meta = _load()["meta"]
    routes = meta["domain"]["routes"]
    parts = [forecast_day(routes)]
    # parts.append(forecast_month(...))
    # parts.append(forecast_year(...))
    df = pd.concat(parts, ignore_index=True)[list(FORECAST_COLUMNS)]
    write_forecast(df, "data/forecast")
    print(f"OK: {len(df)} строк, горизонты: {df['horizon'].unique()}")


if __name__ == "__main__":
    main()
