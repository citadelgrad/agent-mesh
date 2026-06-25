.PHONY: run test lint install jaeger deploy-code-review deploy-security-review undeploy-code-review

install:
	uv sync

run:
	uv run python -m agent_mesh.main

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check agent_mesh/

deploy-code-review:
	uv run --group deploy python -m agent_mesh.specialists.code_review_deploy

deploy-security-review: ## Deploy SecurityReviewAgent to Vertex AI Agent Engine
	uv run --group deploy python -m agent_mesh.specialists.security_review_deploy

undeploy-code-review:
	@if [ -z "$$AGENT_ENGINE_ID" ]; then echo "Set AGENT_ENGINE_ID in .envrc"; exit 1; fi
	uv run --group deploy python -c "\
import vertexai, os; from vertexai import agent_engines; \
vertexai.init(project=os.environ['GOOGLE_CLOUD_PROJECT'], location=os.environ['GOOGLE_CLOUD_LOCATION']); \
agent_engines.get(os.environ['AGENT_ENGINE_ID']).delete()"

jaeger:
	docker run -d --name jaeger \
	  -p 16686:16686 -p 4318:4318 \
	  jaegertracing/all-in-one:latest
	@echo "Jaeger UI: http://localhost:16686"
