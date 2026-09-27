# ML-скелет: прогноз пассажиропотока

## Карта файлов и зачем каждый нужен

| Файл | Что делает | Какие баллы закрывает |
|---|---|---|
| `schema.py` | Контракт forecast.parquet + `validate()`. Фиксируется в день 1, не меняется | защита интеграции |
| `features.py` | Все признаки в одном месте, общие для train и inference | корректная агрегация (2в) |
| `ingest/weather.py` | Open-Meteo: архив + прогноз погоды | источник №1 (2а) |
| `ingest/calendar_ru.py` | isdayoff.ru: праздники, «хвосты», каникулы | источник №2 (2а) |
| `ingest/traffic_events.py` | паттерн трафика + афиша KudaGo | источники №3-4 (2а) |
| `ml/baseline.py` | seasonal naive — точка отсчёта и первый прогноз для бэка | интеграция в день 1 |
| `ml/train.py` | CatBoost + квантили + **ablation.csv** + **meta.json** | 2а (эффект), 2б (домен), 2в (коэфы) |
| `ml/predict.py` | единая точка входа `predict()` для бэкенда | архитектура (3) |
| `ml/batch_forecast.py` | предрасчёт день/месяц/год -> parquet | горизонты (4), latency (3) |
| `Makefile` | `make ingest / train / forecast / test` | воспроизводимость (2в) |

## Порядок работы

```
День 1: schema -> EDA + факт в длинный формат -> baseline -> parquet бэкенду
        -> ingest (4 источника) -> train v1 -> parquet v1
День 2: ablation + meta.json -> месяц/год -> коэффициенты по умолчанию
        -> финальное обучение на всех данных -> parquet v2 -> README
```

## Что нужно доделать (помечено TODO в коде)

1. Загрузка **факта** из выданных данных в `data/fact.parquet`
   (route_id, stop_id, ts_start, pax_in, pax_out) — зависит от формата организаторов.
2. `route_stops.parquet` и вместимость ТС для load_pct.
3. Вторая модель на `pax_out` (тот же train.py, TARGET="pax_out").
4. `forecast_month` / `forecast_year` в batch_forecast.py.
5. `event_nearby`: join событий по радиусу и окну времени.
6. Актуализировать даты каникул в calendar_ru.py.

## Зависимости

```
pandas pyarrow catboost requests
```
Зафиксировать версии в requirements.txt сразу — иначе .cbm/.pkl могут
не загрузиться у бэкенда.
