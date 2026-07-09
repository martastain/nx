VERSION=$(shell sed -n 's/__version__ = \"\(.*\)\"/\1/p' nx/version.py)

check:
	uv version $(VERSION)
	uv run ruff check . --select=I --fix
	uv run ruff format .
	uv run ruff check . --fix
	uv run mypy .

test-integration:
	uv sync --group dev
	docker compose -f docker-compose.test.yml up -d --wait
	trap 'docker compose -f docker-compose.test.yml down' EXIT; \
	NX_POSTGRES_URL=postgresql://nx:nx@127.0.0.1:55432/nx_test \
	NX_REDIS_URL=redis://127.0.0.1:56379/0 \
	uv run pytest -m integration


build: check
	uv build

release: build
	uv publish
	git tag -a v$(VERSION) -m "Release version $(VERSION)"
	git push --tags
