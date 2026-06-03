.PHONY: compose-build compose-up compose-down compose-smoke compose-full ci-integration chaos-spotcheck

compose-build:
	./scripts/setup-compose.sh

compose-up:
	docker compose up -d gateway

compose-down:
	docker compose down

compose-smoke:
	./scripts/compose-integration-smoke.sh

ci-integration:
	./scripts/ci-integration.sh

chaos-spotcheck:
	./scripts/chaos-spotcheck.sh

compose-full:
	docker compose --profile full up -d
