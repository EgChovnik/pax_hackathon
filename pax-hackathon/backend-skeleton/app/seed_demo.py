"""app/seed_demo.py — демо-прогноз (маршрут x час) на 61 день.
Нужен только пока нет submission.csv. Формат тот же.
Запуск: docker compose exec api python -m app.seed_demo"""

import json
import math
import os
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
HOUR = [.04, .03, .02, .02, .04, .14, .42, .85, 1, .88, .55, .45,
        .42, .44, .46, .52, .68, .9, .95, .72, .45, .3, .16, .08]
DOW = [1, 1.02, 1.03, 1.03, 1.06, .62, .5]
ROUTES = [("144", 1.0), ("м27", 1.25), ("908", .8),
          ("с344", .95), ("т25", 1.1), ("263", .7)]
CAP, CNT = 90, 12


def main():
    start = pd.Timestamp.now().floor("D") + pd.Timedelta(days=1)
    rows = []
    for rid, scale in ROUTES:
        for d in range(61):
            day = start + pd.Timedelta(days=d)
            for h in range(24):
                p = 900 * scale * HOUR[h] * DOW[day.dayofweek] \
                    * (1 + .05 * math.sin(d / 4 + scale * 7))
                tr = max(2, round(CNT * HOUR[h] * .95))
                rows.append({"route_id": rid, "ts_start": day + pd.Timedelta(hours=h),
                             "interval": "1h", "horizon": "day",
                             "pax_in": round(p, 1),
                             "load_pct": round(p / (CAP * tr), 3),
                             "pred_low": round(p * .85, 1),
                             "pred_high": round(p * 1.15, 1),
                             "in_domain": True, "model_version": "demo"})
    df = pd.DataFrame(rows)
    out = DATA_DIR / "forecast"
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)
    df.to_parquet(out, partition_cols=["horizon"], index=False)
    (DATA_DIR / "meta.json").write_text(json.dumps({
        "model_version": "demo",
        "domain": {"routes": [r for r, _ in ROUTES]},
        "default_coefs": {"rain": 1.08, "snow": 1.15, "event": 1.3},
        "factors": [
            {"name": "Погода", "source": "https://open-meteo.com/", "effect_pp": 2.4},
            {"name": "Календарь", "source": "https://isdayoff.ru/", "effect_pp": 5.1},
            {"name": "Трафик", "source": "https://data.mos.ru/", "effect_pp": 1.2},
            {"name": "События", "source": "https://docs.kudago.com/api/", "effect_pp": 0.9}],
    }, ensure_ascii=False, indent=2))
    print(f"OK: {len(df)} строк демо-прогноза")


if __name__ == "__main__":
    main()
