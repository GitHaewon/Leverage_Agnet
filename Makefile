.PHONY: dev build test lint migrate shell logs

# ── 개발 환경 ──────────────────────────────────────────────────────────────────
dev:
	docker compose up --build

dev-backend:
	docker compose up backend postgres redis --build

down:
	docker compose down

# ── 마이그레이션 ───────────────────────────────────────────────────────────────
migrate:
	docker compose exec backend alembic upgrade head

migrate-create:
	docker compose exec backend alembic revision --autogenerate -m "$(name)"

migrate-down:
	docker compose exec backend alembic downgrade -1

# ── 테스트 ─────────────────────────────────────────────────────────────────────
test:
	docker compose exec backend pytest tests/ -v

test-unit:
	docker compose exec backend pytest tests/unit/ -v

test-integration:
	BINANCE_TESTNET=true docker compose exec backend pytest tests/integration/ -v

test-cov:
	docker compose exec backend pytest tests/ --cov=app --cov-report=html

# ── 린팅 ──────────────────────────────────────────────────────────────────────
lint:
	docker compose exec backend ruff check app/ tests/
	docker compose exec backend mypy app/

format:
	docker compose exec backend ruff format app/ tests/

# ── 유틸리티 ───────────────────────────────────────────────────────────────────
shell:
	docker compose exec backend python

logs:
	docker compose logs -f backend

logs-all:
	docker compose logs -f

build-prod:
	docker compose -f docker-compose.prod.yml build

health:
	curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
