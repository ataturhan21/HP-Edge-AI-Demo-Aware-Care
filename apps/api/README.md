# Backend implementation boundary

The FastAPI application is implemented (`app/`, with `uv.lock`), and `tests/acceptance` holds its acceptance tests (333 on
the `v0.8.3-demo.1` commit; `uv run pytest --collect-only -q` counts the current ones). At handoff, no HTTP application
existed. Use the project environment; never install into ZRT or system Python.

The authoritative operations are ../../spec/api/openapi.json. Module ownership is ../../spec/modules.json. Create app/modules/<owner>/routes.py, schemas.py, service.py and repository.py only where persistence is owned. Enforce actor/role/consent, Origin/CSRF, idempotency and case revision checks server-side. Generate the frontend API client from OpenAPI.

The proposed local API listens on 127.0.0.1:8000, with /api/v1 prefix. ZRT is a separate existing service whose documented default is 127.0.0.1:8080/v1. Do not install app packages into ZRT or expose its credentials through patient responses. Use persistent local storage appropriate to the demo; SQLite is a proposed initial database choice, not an excuse to skip transactions or migrations.

runtime/adapter.py is the interface contract. `runtime/mock_provider.py` and `runtime/zrt_provider.py` implement it, and
`runtime/metering.py` wraps it for the W06 telemetry. Content gates prevent local clinical guidance without an enabled
reviewed pathway: `general-adult-4` is enabled (ADR-003), and there is no corpus (ADR-004). Backend mock mode still needs real session, ownership, revision, deletion and retention behavior; only its inference/directory/content are synthetic.

## Development build (CHG-DEV-APP-001)

Isolated uv environment in `apps/api/.venv`; never install into ZRT or system Python.

```bash
cd apps/api
uv sync --python 3.12.15            # install pinned deps from uv.lock (incl. jsonschema, and the dev group: pytest)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
curl --fail --show-error --silent --max-time 5 http://127.0.0.1:8000/api/v1/health/ready
uv run pytest                        # runs ../../tests/acceptance (mock mode, no ZRT contact)
```

Server-only configuration follows `infra/.env.example` (`AWARECARE_MODE=mock` default), which lists every variable
the API reads (`app/config.py`, plus `AWARECARE_APP_COMMIT` in the operations and metering code), among them
`AWARECARE_ALLOWED_ORIGINS` (default `http://127.0.0.1:15173`, the SSH-tunnel browser origin),
`AWARECARE_COOKIE_SECURE` (default `false`, development-only for HTTP over the tunnel),
`AWARECARE_DATA_DIR` (default `runtime-data/api`, git-ignored; SQLite + export files).
Reset all local demo data: stop the API, delete `runtime-data/api/`, start again.
Interpretations and open gaps: `spec/decisions/ADR-007-dev-mock-build.md`.
