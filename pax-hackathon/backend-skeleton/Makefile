# Команды бэкендера. Полная инструкция — в README.md

up:              ## собрать и поднять postgres + api
	docker compose up -d --build

submission:      ## ГЛАВНОЕ СЕГОДНЯ: загрузить data/submission.csv в API
	docker compose exec api python -m app.load_submission
	curl -s -X POST localhost:8000/admin/reload && echo

seed:            ## демо-прогноз, если submission.csv ещё нет
	docker compose exec api python -m app.seed_demo
	curl -s -X POST localhost:8000/admin/reload && echo

logs:            ## логи API
	docker compose logs -f api

psql:            ## консоль Postgres
	docker compose exec postgres psql -U pax -d pax

test:            ## дымовой тест всех эндпоинтов
	curl -sf localhost:8000/health && echo
	curl -sf localhost:8000/routes | head -c 300 && echo
	curl -sf "localhost:8000/forecast?limit=3" && echo
	curl -sf "localhost:8000/alerts" | head -c 500 && echo
	curl -sf "localhost:8000/recommendations" | head -c 500 && echo
	curl -sf "localhost:8000/export?format=csv" -o /tmp/f.csv && head -3 /tmp/f.csv

loadtest:        ## цифры latency/RPS для README (нужен hey)
	hey -z 15s -c 50 "http://localhost:8000/forecast?horizon=day&limit=5000"

ml-update:       ## перечитать meta после обновления data/
	curl -s -X POST localhost:8000/admin/reload && echo

down:
	docker compose down

reset:           ## полный сброс, включая том БД
	docker compose down -v
