# Бэкенд: прогноз пассажиропотока — от нуля до работающего API

Архитектура: **Postgres** хранит справочники (маршруты, остановки, ТС) и
коэффициенты; **прогноз лежит в parquet** (кладёт ML) и читается **DuckDB**
с пушдауном фильтров — поэтому API отвечает за миллисекунды без прогрева.

```
data/forecast/**.parquet  ←  ML (batch_forecast)
data/meta.json            ←  ML (train)
Postgres                  ←  db/init.sql (справочники, coef_defaults)
FastAPI :8000             →  фронтенд (CORS открыт)
```

## Шаг 0. Установить Docker (один раз)

**Ubuntu / Debian:**
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER   # затем перелогиниться (или: newgrp docker)
docker compose version           # проверка
```

**macOS / Windows:** поставить Docker Desktop с docker.com, запустить его,
проверить `docker compose version` в терминале.

## Шаг 1. Поднять всё

```bash
cd backend-skeleton
docker compose up -d --build     # или: make up
docker compose ps                # оба сервиса должны быть healthy/running
```

При первом старте Postgres сам накатывает `db/init.sql` — схема и
демо-справочники уже в базе, отдельных миграций не нужно.

## Шаг 2. Загрузить submission.csv (главный шаг)

```bash
cp /путь/к/submission.csv ./data/submission.csv
make submission          # распознает колонки, посчитает load_pct, перечитает meta
```

Колонки распознаются автоматически: маршрут (route_id/route/маршрут…), время
(ts/datetime… или date+hour; форматы 2026-10-01 08:00 и 01.10.2026 8),
значение (pred/y/pax/пассажиропоток…). Разделитель `,`/`;`, кодировка
utf-8/cp1251, десятичная запятая — всё понимается. Если имена колонок
экзотические — допишите их в списки `*_COLS` в `app/load_submission.py`.

## Шаг 2-бис. Демо-прогноз (если submission.csv ещё нет)

```bash
docker compose exec api python -m app.seed_demo    # или: make seed
```

Пишет в `./data/` прогноз на 7 дней и meta.json — тот же формат,
который позже отдаст ML.

## Шаг 3. Проверить, что всё живо

```bash
make test        # дымовой прогон всех эндпоинтов
```

или руками:

```bash
curl localhost:8000/health
curl "localhost:8000/forecast?horizon=day&limit=3"
curl "localhost:8000/alerts"
curl "localhost:8000/recommendations"
curl "localhost:8000/coefs/defaults"
curl -X POST localhost:8000/forecast/adjust \
  -H "Content-Type: application/json" \
  -d '{"coefs":{"snow":1.15,"event":1.3}}' | head -c 400
curl -o forecast.xlsx "localhost:8000/export?format=xlsx"
```

Swagger со всеми схемами: **http://localhost:8000/docs**
(фронтендер генерирует типы: `npx openapi-typescript http://localhost:8000/openapi.json -o api.d.ts`)

## Шаг 4. Обновление прогноза от ML

Новый submission.csv → снова `make submission`. Перезапуск контейнеров не
нужен: parquet читается лениво, замена атомарна (папка пересоздаётся целиком).

## Шаг 5. Цифры для README (критерий 3)

```bash
# установить hey: https://github.com/rakyll/hey  (или: go install github.com/rakyll/hey@latest)
make loadtest
```

Ожидаемо на ноутбуке: p95 в единицы–десятки мс, сотни–тысячи RPS.
Скопируйте вывод hey в README проекта вместе с командой запуска —
жюри засчитывает честную самооценку с подтверждением.

## Отладка

```bash
make logs                        # логи API
make psql                        # консоль БД: \dt — список таблиц
docker compose restart api       # перезапуск после правок кода
make reset                       # снести всё вместе с БД и начать заново
```

| Симптом | Причина и лечение |
|---|---|
| `/forecast` пустой | `make submission` (файл в ./data/) или `make seed` |
| `connection refused` к БД | Postgres ещё стартует: `docker compose ps`, ждать healthy |
| порт 8000 занят | поменять маппинг в docker-compose.yml на `8001:8000` |
| правки init.sql не применились | схема ставится только на пустой том: `make reset && make up` |

## Карта файлов

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | Postgres + API, том `./data` для parquet от ML |
| `db/init.sql` | вся схема БД + демо-справочники |
| `app/main.py` | эндпоинты: forecast, adjust, alerts, recommendations, export, meta, factors, health |
| `app/store.py` | DuckDB по parquet + Postgres + кэш meta.json |
| `app/services.py` | окна перегрузок и рекомендации «добавить N ТС» |
| `app/schemas.py` | pydantic-контракт (фронт берёт типы из /openapi.json) |
| `app/load_submission.py` | загрузка submission.csv → parquet (главный файл) |
| `app/seed_demo.py` | демо-прогноз, пока submission.csv нет |

## Примечание про остановки

Таблицы `stops`, `route_stops`, `pax_fact` в init.sql остались от версии 1 —
они не используются и не мешают. `vehicles` используется для расчёта
load_pct; маршруты, которых нет в таблице, получают дефолт 90 мест × 12 машин
(константы DEFAULT_* в app/load_submission.py и services.py).
