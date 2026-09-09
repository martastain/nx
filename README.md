# nx
Very opinionated set of tools

## Testing

Run the fast test suite with:

```bash
uv run pytest -m "not integration"
```

Run the integration suite against Docker-backed Postgres and Redis with:

```bash
make test-integration
```

That starts the services, runs the suite and tears them down again. To iterate
against a stack you keep running yourself:

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest -m integration
docker compose -f docker-compose.test.yml down
```

`NX_POSTGRES_URL` and `NX_REDIS_URL` override the services the suite connects
to; they default to the ports in `docker-compose.test.yml`. Each test works in
its own Redis namespace and its own Postgres table, so the suite can be re-run
against long-lived services without resetting them.
