.PHONY: install playground run test lint run-web

install:
	uv sync

playground:
	uv run adk web app --host 127.0.0.1 --port 18081 --reload_agents

run:
	uv run adk api_server app --host 127.0.0.1 --port 8080

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check app/

run-web:
	uv run uvicorn app.web_server:app --host 127.0.0.1 --port 8000
