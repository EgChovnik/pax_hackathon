# Воспроизводимый пайплайн (= балл критерия 2в за пайплайн приёма данных)
# Порядок дня 1: make ingest -> make train -> make forecast

ingest:            ## скачать внешние источники в data/
	python -m ingest.weather
	python -m ingest.calendar_ru
	python -m ingest.traffic_events

train:             ## обучить модель, ablation, meta.json
	python -m ml.train

forecast:          ## предрасчёт прогнозов -> data/forecast/ (читает бэкенд)
	python -m ml.batch_forecast

test:              ## эталонный прогон predict() — гоняет и бэкенд после интеграции
	python -c "from ml.predict import predict; \
	df = predict(['144'], '2026-09-28', '2026-09-29'); \
	print(df.head()); assert len(df) > 0"

all: ingest train forecast
