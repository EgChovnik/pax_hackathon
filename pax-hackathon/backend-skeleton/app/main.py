"""app/main.py — REST API (маршрутный уровень). Swagger: localhost:8000/docs"""

import io
import json
import time
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from . import services, store
from .schemas import AdjustRequest, Alert, Factor, ForecastRow, Recommendation

app = FastAPI(title="Пассажиропоток Москвы", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    t0 = time.perf_counter()
    df = store.query_forecast()
    return {"status": "ok", "forecast_rows": int(len(df)),
            "routes": int(df["route_id"].nunique()) if len(df) else 0,
            "model_version": store.meta().get("model_version"),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


@app.get("/meta")
def meta():
    return store.meta()


@app.get("/factors", response_model=list[Factor])
def factors():
    return [Factor(name=f.get("name", "?"), source=f.get("source", ""),
                   effect_pp=f.get("effect_pp"))
            for f in store.meta().get("factors", [])]


@app.get("/routes")
def routes():
    """Маршруты из прогноза + имена/парк из Postgres, если есть."""
    df = store.query_forecast()
    ids = sorted(df["route_id"].unique().tolist()) if len(df) else []
    try:
        info = {r["route_id"]: r for r in store.pg_rows(
            "select r.route_id, r.name, r.color, v.capacity, v.count as vehicles "
            "from routes r left join vehicles v using(route_id)")}
    except Exception:
        info = {}
    return [{"route_id": i, **info.get(i, {"name": "Маршрут " + i})} for i in ids]


@app.get("/forecast", response_model=list[ForecastRow])
def forecast(route_id: str | None = None,
             ts_from: datetime | None = None, ts_to: datetime | None = None,
             horizon: str = Query("day", pattern="^(day|month|year)$"),
             limit: int = Query(5000, le=200000)):
    df = store.query_forecast(route_id, ts_from, ts_to, horizon)
    return df.head(limit).to_dict("records")


@app.post("/forecast/adjust", response_model=list[ForecastRow])
def forecast_adjust(req: AdjustRequest):
    df = store.query_forecast(req.route_id, req.ts_from, req.ts_to, req.horizon)
    return store.apply_coefs(df, req.coefs).to_dict("records")


@app.get("/coefs/defaults")
def coef_defaults():
    try:
        return store.pg_rows("select factor, multiplier, note from coef_defaults")
    except Exception:
        return [{"factor": k, "multiplier": v, "note": None}
                for k, v in store.meta().get("default_coefs", {}).items()]


def _parse_coefs(coefs: str | None) -> dict:
    return json.loads(coefs) if coefs else {}


def _day(date: datetime | None) -> datetime:
    if date is None:
        df = store.query_forecast()
        date = df["ts_start"].min() if len(df) else datetime.now() + timedelta(days=1)
    return date.replace(hour=0, minute=0, second=0, microsecond=0)


@app.get("/alerts", response_model=list[Alert])
def alerts(date: datetime | None = None, coefs: str | None = None):
    return services.alerts(_day(date), _parse_coefs(coefs))


@app.get("/recommendations", response_model=list[Recommendation])
def recommendations(date: datetime | None = None, coefs: str | None = None):
    return services.recommendations(_day(date), _parse_coefs(coefs))


@app.get("/export")
def export(format: str = Query("csv", pattern="^(csv|xlsx)$"),
           route_id: str | None = None,
           ts_from: datetime | None = None, ts_to: datetime | None = None,
           horizon: str = "day", coefs: str | None = None):
    df = store.apply_coefs(
        store.query_forecast(route_id, ts_from, ts_to, horizon),
        _parse_coefs(coefs))
    if df.empty:
        raise HTTPException(404, "по этим параметрам прогноза нет")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if format == "csv":
        return Response(df.to_csv(index=False, sep=";"),
                        media_type="text/csv",
                        headers={"Content-Disposition":
                                 f'attachment; filename="forecast_{stamp}.csv"'})
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument"
                               ".spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             f'attachment; filename="forecast_{stamp}.xlsx"'})


@app.post("/admin/reload")
def admin_reload():
    store.reload_meta()
    return {"status": "reloaded",
            "model_version": store.meta().get("model_version")}
