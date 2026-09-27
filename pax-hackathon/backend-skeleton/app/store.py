"""app/store.py — прогноз из parquet через DuckDB, справочники из Postgres."""

import json
import os
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd
import psycopg2
import psycopg2.extras

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DB_URL = os.getenv("DATABASE_URL", "postgresql://pax:pax@localhost:5432/pax")

_duck = duckdb.connect()

ADJUST_COLS = ("pax_in", "load_pct", "pred_low", "pred_high")


def pg():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def pg_rows(sql: str, params=()):
    with pg() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def forecast_glob() -> str:
    return str(DATA_DIR / "forecast" / "**" / "*.parquet")


def query_forecast(route_id=None, ts_from=None, ts_to=None,
                   horizon="day") -> pd.DataFrame:
    sql = f"select * from read_parquet('{forecast_glob()}', hive_partitioning=1) where horizon = ?"
    params: list = [horizon]
    if route_id:
        sql += " and route_id = ?";  params.append(route_id)
    if ts_from:
        sql += " and ts_start >= ?"; params.append(ts_from)
    if ts_to:
        sql += " and ts_start < ?";  params.append(ts_to)
    sql += " order by route_id, ts_start"
    try:
        return _duck.execute(sql, params).df()
    except duckdb.IOException:
        return pd.DataFrame(columns=["route_id", "ts_start", "interval", "horizon",
                                     "pax_in", "load_pct", "pred_low", "pred_high",
                                     "in_domain", "model_version"])


def apply_coefs(df: pd.DataFrame, coefs: dict[str, float]) -> pd.DataFrame:
    k = 1.0
    for v in coefs.values():
        k *= float(v)
    if abs(k - 1) < 1e-9 or df.empty:
        return df
    df = df.copy()
    for col in ADJUST_COLS:
        if col in df.columns:
            df[col] = df[col] * k
    return df


@lru_cache(maxsize=1)
def meta() -> dict:
    p = DATA_DIR / "meta.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"model_version": "demo", "metrics": {}, "factors": [],
            "domain": {"routes": []}, "default_coefs": {}}


def reload_meta():
    meta.cache_clear()
