.PHONY: run test lint install jaeger

install:
	uv sync

run:
	uv run python -m agent_mesh.main

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check agent_mesh/

jaeger:
	docker run -d --name jaeger \
	  -p 16686:16686 -p 4318:4318 \
	  jaegertracing/all-in-one:latest
	@echo "Jaeger UI: http://localhost:16686"
