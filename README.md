# nx
Very opinionated set of tools

## Testing

Run the fast test suite with:

```bash
uv run pytest -m "not integration"
```

Run the integration suite against Docker-backed Postgres and Redis with:

```bash
docker compose -f docker-compose.test.yml up -d
NX_POSTGRES_URL=postgresql://nx:nx@127.0.0.1:55432/nx_test \
NX_REDIS_URL=redis://127.0.0.1:56379/0 \
uv run pytest -m integration
docker compose -f docker-compose.test.yml down
```
