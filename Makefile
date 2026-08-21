.PHONY: dev-api dev-ui install test test-all build docker fmt

install:
	cd backend && python3 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install

dev-api:
	cd backend && BUC_DATA_DIR=../data ./.venv/bin/uvicorn app.main:app --reload --port 8000

dev-ui:
	cd frontend && npm run dev

test:                    ## fast suite -- ffmpeg stubbed out
	cd backend && ./.venv/bin/python -m pytest -q --ignore=tests/test_integration.py

test-all:                ## includes the real-ffmpeg pipeline test
	cd backend && ./.venv/bin/python -m pytest -q

build:
	cd frontend && npm run build

docker:
	docker compose up --build
