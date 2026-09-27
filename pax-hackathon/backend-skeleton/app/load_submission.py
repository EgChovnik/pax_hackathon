"""app/load_submission.py — превращает submission.csv от ML в прогноз API.

Кладёте файл в ./data/submission.csv и запускаете:
    docker compose exec api python -m app.load_submission
(или make submission). Затем make ml-update. Всё.

Колонки распознаются автоматически (регистр не важен):
    маршрут:  route_id / route / route_number / маршрут / line
    время:    ts / ts_start / datetime / timestamp  ИЛИ  date+hour (дата+час)
              форматы: 2026-10-01 08:00, 2026-10-01T08:00, 01.10.2026 8
    значение: pax / pax_in / passengers / pred / prediction / y / y_pred /
              value / target / пассажиропоток
Разделитель , или ; и десятичная запятая понимаются сами.
Если имена другие — впишите их первыми в списки *_COLS ниже.

load_pct считается как pax / (вместимость x рейсов в час):
вместимость и парк берутся из таблицы vehicles, для незнакомых маршрутов —
дефолт 90 мест x 12 машин (поправьте DEFAULT_* под вашу сеть).
"""

import json
import math
import os
import sys
from pathlib import Path

import pandas as pd

from .store import pg_rows

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))

ROUTE_COLS = ["route_id", "route", "route_number", "маршрут", "line", "bus", "id_route"]
TS_COLS = ["ts", "ts_start", "datetime", "date_time", "timestamp", "time", "дата_время"]
DATE_COLS = ["date", "дата", "day"]
HOUR_COLS = ["hour", "час", "hr", "h"]
VAL_COLS = ["pax", "pax_in", "passengers", "prediction", "pred", "y", "y_pred",
            "value", "count", "target", "пассажиропоток", "flow"]

DEFAULT_CAPACITY = 90
DEFAULT_VEHICLES = 12
HOUR_PROFILE = [.04, .03, .02, .02, .04, .14, .42, .85, 1, .88, .55, .45,
                .42, .44, .46, .52, .68, .9, .95, .72, .45, .3, .16, .08]


def read_csv_flexible(path: Path) -> pd.DataFrame:
    for enc in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            head = path.read_text(encoding=enc)[:2000]
            sep = ";" if head.count(";") > head.count(",") else ","
            return pd.read_csv(path, sep=sep, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    raise SystemExit("Не смог прочитать файл ни в utf-8, ни в cp1251")


def pick(cols, cands):
    low = {c.lower().strip(): c for c in cols}
    for c in cands:
        if c in low:
            return low[c]
    return None


def main(path: str = None):
    src = Path(path or DATA_DIR / "submission.csv")
    if not src.exists():
        raise SystemExit(f"Нет файла {src} — положите submission.csv в ./data/")

    df = read_csv_flexible(src)
    c_route = pick(df.columns, ROUTE_COLS)
    c_ts = pick(df.columns, TS_COLS)
    c_date, c_hour = pick(df.columns, DATE_COLS), pick(df.columns, HOUR_COLS)
    c_val = pick(df.columns, VAL_COLS)
    if c_val is None:  # первая числовая, не занятая ключами
        for c in df.columns:
            if c in (c_route, c_ts, c_date, c_hour):
                continue
            if pd.to_numeric(df[c].str.replace(",", "."), errors="coerce").notna().mean() > .9:
                c_val = c
                break
    if not c_route or not c_val or not (c_ts or c_date):
        raise SystemExit(
            f"Не распознал колонки. В файле: {list(df.columns)}.\n"
            f"Нашёл: маршрут={c_route}, время={c_ts or c_date}, значение={c_val}.\n"
            f"Допишите ваши имена в *_COLS в начале app/load_submission.py")
    print(f"Колонки: маршрут='{c_route}', время='{c_ts or c_date}'"
          f"{f'+час={c_hour!r}' if c_hour and not c_ts else ''}, значение='{c_val}'")

    def parse_dt(s: pd.Series) -> pd.Series:
        """Сначала ISO (2026-10-01[ 08:00]), затем DD.MM.YYYY —
        иначе dayfirst перевернёт ISO-даты."""
        s = s.astype(str).str.strip()
        iso = pd.to_datetime(s, errors="coerce", format="ISO8601")
        rest = iso.isna()
        if rest.any():
            iso[rest] = pd.to_datetime(s[rest], errors="coerce", dayfirst=True)
        return iso

    out = pd.DataFrame({
        "route_id": df[c_route].astype(str).str.strip(),
        "pax_in": pd.to_numeric(df[c_val].str.replace(",", "."), errors="coerce"),
    })
    if c_ts:
        out["ts_start"] = parse_dt(df[c_ts])
    else:
        d = parse_dt(df[c_date])
        h = pd.to_numeric(df[c_hour], errors="coerce") if c_hour else 0
        out["ts_start"] = d + pd.to_timedelta(h, unit="h")

    n0 = len(out)
    out = out.dropna()
    out = out[out["pax_in"] >= 0]
    if out.empty:
        raise SystemExit("Все строки отбраковались — проверьте формат времени")
    # дубли (маршрут, час) складываем
    out = out.groupby(["route_id", "ts_start"], as_index=False)["pax_in"].sum()

    veh = {}
    try:
        veh = {r["route_id"]: r for r in pg_rows(
            "select route_id, capacity, count from vehicles")}
    except Exception:
        print("Postgres недоступен — беру вместимость по умолчанию")

    # Автокалибровка. Реальных данных о выпуске ТС нет, поэтому:
    # 1) профиль рейсов маршрута = его собственный средний профиль спроса
    #    по часам (нормированный, с полом 0.15 — ночью рейсы редкие,
    #    но не нулевые);
    # 2) парк подбирается так, чтобы ТИПИЧНЫЙ пик давал ~92% заполненности.
    # Тогда load_pct читается как «насколько час тяжелее типичного»,
    # и алерты подсвечивают настоящие аномалии (праздники, выбросы),
    # а не несоответствие взятому с потолка дефолту.
    # Когда появятся реальные вместимость и парк — внесите их в таблицу
    # vehicles, для этих маршрутов оценка не используется.
    hcol = out["ts_start"].dt.hour
    mean_prof = out.assign(h=hcol).groupby(["route_id", "h"])["pax_in"].mean()
    profs: dict[str, list[float]] = {}
    for rid in out["route_id"].unique():
        arr = mean_prof.loc[rid].reindex(range(24)).fillna(0.0)
        profs[rid] = (arr / max(float(arr.max()), 1.0)).clip(lower=0.15).tolist()

    need = out.assign(
        p=[profs[r][h] for r, h in zip(out["route_id"], hcol)])
    need = (need["pax_in"] / need["p"]).groupby(out["route_id"]).max()
    veh_est = {rid: max(4, math.ceil(v / (DEFAULT_CAPACITY * 0.92)))
               for rid, v in need.items() if rid not in veh}
    if veh_est:
        print("Парк оценён из типичного пика (маршрут: машин):",
              dict(sorted(veh_est.items(), key=lambda x: x[0])))

    def load_row(r):
        v = veh.get(r.route_id) or {"capacity": DEFAULT_CAPACITY,
                                    "count": veh_est.get(r.route_id,
                                                         DEFAULT_VEHICLES)}
        tr = max(2, round(v["count"] * profs[r.route_id][r.ts_start.hour]))
        return r.pax_in / (v["capacity"] * tr)

    out["load_pct"] = out.apply(load_row, axis=1).round(3)
    out["pred_low"] = (out["pax_in"] * 0.85).round(1)
    out["pred_high"] = (out["pax_in"] * 1.15).round(1)
    out["interval"] = "1h"
    out["horizon"] = "day"
    out["in_domain"] = True
    out["model_version"] = "submission"

    dst = DATA_DIR / "forecast"
    if dst.exists():
        import shutil
        shutil.rmtree(dst)
    out.to_parquet(dst, partition_cols=["horizon"], index=False)

    meta_p = DATA_DIR / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    meta.update({
        "model_version": "submission",
        "vehicles_est": veh_est,
        "domain": {"routes": sorted(out["route_id"].unique().tolist())},
        "period": [str(out["ts_start"].min()), str(out["ts_start"].max())],
    })
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"OK: {len(out)} строк (из {n0} в файле), "
          f"маршрутов {out['route_id'].nunique()}, "
          f"период {out['ts_start'].min():%d.%m %H:%M} — {out['ts_start'].max():%d.%m %H:%M}")
    print("Дальше: curl -X POST localhost:8000/admin/reload  (или make ml-update)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
