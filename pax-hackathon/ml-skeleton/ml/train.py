"""
ml/train.py — обучение. На выходе три вещи, каждая = баллы:

1. models/v1/model.cbm (+ квантильные модели) — сам прогноз.
2. models/v1/meta.json — область применимости (критерий 2б) +
   коэффициенты по умолчанию для слайдеров (критерий 2в).
3. models/v1/ablation.csv — подтверждение эффекта источников (критерий 2а):
   таблица «убрали фактор -> насколько выросла ошибка». Идёт в README
   и в API /factors.

Валидация ТОЛЬКО по времени: последние 1-2 недели = holdout.
Финальный прогон перед сдачей — обучение на всех данных.
"""

import json
from pathlib import Path

import pandas as pd
from catboost import CatBoostRegressor

from features import build_features, FEATURES, CAT_FEATURES
from ml.baseline import mape

TARGET = "pax_in"          # вторую модель — на pax_out, тем же кодом
HOLDOUT_DAYS = 14
MODEL_DIR = Path("models/v1")

# группы признаков для ablation: имя источника -> его колонки
ABLATION_GROUPS = {
    "weather": ["temp", "precip_mm", "is_rain", "is_snow"],
    "calendar": ["is_holiday", "day_before_holiday",
                 "day_after_holiday", "is_school_break"],
    "traffic": ["congestion"],
    "events": ["event_nearby"],
}


def split_by_time(df):
    cut = df["ts_start"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    return df[df["ts_start"] <= cut], df[df["ts_start"] > cut]


def fit(train, features, loss="RMSE"):
    model = CatBoostRegressor(
        loss_function=loss, iterations=800, verbose=200,
        cat_features=[f for f in CAT_FEATURES if f in features])
    model.fit(train[features], train[TARGET])
    return model


def run_ablation(train, test, base_mape):
    rows = [{"factor": "full_model", "mape": base_mape, "delta": 0.0}]
    for name, cols in ABLATION_GROUPS.items():
        feats = [f for f in FEATURES if f not in cols]
        m = fit(train, feats)
        s = mape(test[TARGET], pd.Series(m.predict(test[feats])))
        rows.append({"factor": name, "mape": s, "delta": s - base_mape})
    return pd.DataFrame(rows)


def default_coefs(model, test):
    """Коэффициенты для слайдеров — из модели, не с потолка:
    средний прогноз при условии / без условия."""
    pred = pd.Series(model.predict(test[FEATURES]), index=test.index)

    def ratio(mask):
        if mask.sum() < 30 or (~mask).sum() < 30:
            return 1.0
        return round(pred[mask].mean() / pred[~mask].mean(), 3)

    return {
        "rain": ratio(test["is_rain"] == 1),
        "snow": ratio(test["is_snow"] == 1),
        "holiday": ratio(test["is_holiday"] == 1),
        "school_break": ratio(test["is_school_break"] == 1),
    }


def build_meta(df, model, metrics, coefs):
    """Область применимости (2б) генерируется автоматически из данных."""
    return {
        "model_version": "v1",
        "trained_at": str(pd.Timestamp.now().date()),
        "train_period": [str(df["ts_start"].min()), str(df["ts_start"].max())],
        "domain": {
            "routes": sorted(df["route_id"].unique().tolist()),
            "horizons_trained": ["day"],
            "feature_ranges": {"temp": [float(df["temp"].min()),
                                        float(df["temp"].max())]},
        },
        "metrics": metrics,
        "default_coefs": coefs,
        "factors": [
            {"name": "weather", "source": "https://open-meteo.com/"},
            {"name": "calendar", "source": "https://isdayoff.ru/"},
            {"name": "traffic", "source": "https://data.mos.ru/"},
            {"name": "events", "source": "https://docs.kudago.com/api/"},
        ],
    }


def main():
    fact = pd.read_parquet("data/fact.parquet")
    weather = pd.read_parquet("data/weather.parquet").rename(columns={})
    calendar = pd.read_parquet("data/calendar.parquet")
    traffic = pd.read_parquet("data/traffic.parquet")

    df = build_features(fact, weather=weather, calendar=calendar,
                        traffic=traffic)
    train, test = split_by_time(df)

    model = fit(train, FEATURES)
    pred = pd.Series(model.predict(test[FEATURES]), index=test.index)
    base_mape = mape(test[TARGET], pred)

    # квантили для доверительного интервала (pred_low / pred_high)
    q10 = fit(train, FEATURES, loss="Quantile:alpha=0.1")
    q90 = fit(train, FEATURES, loss="Quantile:alpha=0.9")

    ablation = run_ablation(train, test, base_mape)
    coefs = default_coefs(model, test)
    meta = build_meta(df, model, {"MAPE_day": round(base_mape, 4)}, coefs)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_DIR / "model.cbm")
    q10.save_model(MODEL_DIR / "model_q10.cbm")
    q90.save_model(MODEL_DIR / "model_q90.cbm")
    ablation.to_csv(MODEL_DIR / "ablation.csv", index=False)
    (MODEL_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"MAPE={base_mape:.3f}")
    print(ablation)


if __name__ == "__main__":
    main()
