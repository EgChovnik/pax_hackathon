"""app/schemas.py — контракт API (маршрутный уровень, без остановок).
Фронт генерирует типы из /openapi.json."""

from datetime import datetime
from pydantic import BaseModel, Field


class ForecastRow(BaseModel):
    route_id: str
    ts_start: datetime
    interval: str = "1h"
    horizon: str = "day"
    pax_in: float
    load_pct: float
    pred_low: float
    pred_high: float
    in_domain: bool = True
    model_version: str = "v1"


class AdjustRequest(BaseModel):
    """Что-если: фильтры + множители. Модель не перезапускается."""
    route_id: str | None = None
    ts_from: datetime | None = None
    ts_to: datetime | None = None
    horizon: str = Field("day", pattern="^(day|month|year)$")
    coefs: dict[str, float] = Field(default_factory=dict,
                                    examples=[{"rain": 1.15, "event": 1.3}])


class Alert(BaseModel):
    route_id: str
    ts_from: datetime
    ts_to: datetime
    peak_load_pct: float


class Recommendation(BaseModel):
    route_id: str
    window: str
    peak_load_pct: float
    action: str
    effect_load_pct: float
    passengers_affected: int


class Factor(BaseModel):
    name: str
    source: str
    effect_pp: float | None = None
