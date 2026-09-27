"""app/services.py — перевод прогноза в решения. Маршрутный уровень."""

import math

import pandas as pd

from .store import meta, pg_rows, query_forecast, apply_coefs

OVERLOAD = 0.95
TARGET = 0.92
DEFAULT_VEH = {"capacity": 90, "count": 12}


def _vehicles() -> dict[str, dict]:
    """Таблица vehicles, дополненная оценками парка из load_submission
    (vehicles_est в meta.json) — те же числа, что участвуют в load_pct."""
    try:
        out = {r["route_id"]: r for r in pg_rows(
            "select route_id, capacity, count from vehicles")}
    except Exception:
        out = {}
    for rid, n in meta().get("vehicles_est", {}).items():
        out.setdefault(rid, {"capacity": DEFAULT_VEH["capacity"], "count": n})
    return out


def _windows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    hourly = (df.assign(h=df["ts_start"].dt.floor("h"))
                .groupby(["route_id", "h"])["load_pct"].max().reset_index())
    hourly = hourly[hourly["load_pct"] > OVERLOAD].sort_values(["route_id", "h"])
    out: list[dict] = []
    for r in hourly.itertuples():
        prev = out[-1] if out else None
        if prev and prev["route_id"] == r.route_id and r.h == prev["ts_to"]:
            prev["ts_to"] = r.h + pd.Timedelta(hours=1)
            prev["peak"] = max(prev["peak"], r.load_pct)
        else:
            out.append({"route_id": r.route_id, "ts_from": r.h,
                        "ts_to": r.h + pd.Timedelta(hours=1), "peak": r.load_pct})
    return sorted(out, key=lambda x: -x["peak"])


def _day_df(date, coefs):
    return apply_coefs(
        query_forecast(ts_from=date, ts_to=date + pd.Timedelta(days=1)), coefs)


def alerts(date, coefs: dict) -> list[dict]:
    return [{"route_id": w["route_id"], "ts_from": w["ts_from"],
             "ts_to": w["ts_to"], "peak_load_pct": round(float(w["peak"]), 3)}
            for w in _windows(_day_df(date, coefs))]


def recommendations(date, coefs: dict) -> list[dict]:
    df = _day_df(date, coefs)
    veh = _vehicles()
    recs = []
    for w in _windows(df):
        v = veh.get(w["route_id"], DEFAULT_VEH)
        add = max(1, math.ceil(v["count"] * (w["peak"] / TARGET) - v["count"]))
        after = w["peak"] * v["count"] / (v["count"] + add)
        win = df[(df["route_id"] == w["route_id"])
                 & (df["ts_start"] >= w["ts_from"])
                 & (df["ts_start"] < w["ts_to"])]
        recs.append({
            "route_id": w["route_id"],
            "window": f'{w["ts_from"]:%H:%M}–{w["ts_to"]:%H:%M}',
            "peak_load_pct": round(float(w["peak"]), 3),
            "action": f"добавить {add} ТС",
            "effect_load_pct": round(float(after), 3),
            "passengers_affected": int(win["pax_in"].sum()),
        })
    return recs
