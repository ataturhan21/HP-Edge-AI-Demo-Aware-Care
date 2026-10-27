# Aware Care API package (M12; R34, R37, R38). Built for linux/arm64 by
# .github/workflows/release.yml; the build context is the repository root.
# The image holds code, the locked dependencies, the synthetic fixture pack, the
# reviewed pathway packages and the observational infra records only. Runtime data is a host bind mount at
# /var/lib/aware-care/data; mode, origins and ports are passed at `docker run`.
# No credential, model weight, ZRT component or GPU library is installed here.
ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/srv/aware-care/apps/api/.venv
WORKDIR /srv/aware-care/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM ${PYTHON_IMAGE}
ARG APP_COMMIT=unknown
LABEL org.opencontainers.image.title="aware-care-api" \
      org.opencontainers.image.source="<your-repo-url>" \
      org.opencontainers.image.revision="${APP_COMMIT}" \
      org.opencontainers.image.description="Aware Care API. Synthetic demonstration; not for clinical use." \
      io.aware-care.capabilities="scenario-handoff,local-scenarios,quick-demos,quick-flows"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/srv/aware-care/apps/api/.venv/bin:$PATH \
    AWARECARE_DATA_DIR=/var/lib/aware-care/data
# app/config.py resolves fixtures/ and infra/*.json from the repository root
# (three levels above app/config.py), so the image keeps that layout.
WORKDIR /srv/aware-care/apps/api
COPY --from=build /srv/aware-care/apps/api/.venv ./.venv
COPY apps/api/app ./app
COPY fixtures /srv/aware-care/fixtures
# Reviewed pathway packages (ADR-003); app/config.py resolves content/pathways from the repository root too.
COPY content/pathways /srv/aware-care/content/pathways
COPY infra/model-manifest.json infra/device-inventory.json infra/telemetry-pricing.json /srv/aware-care/infra/
# ADR-018: the ZGX Fury's model manifest, inventory and prices; its deploy configuration selects them.
COPY infra/fury/model-manifest.json infra/fury/device-inventory.json infra/fury/telemetry-pricing.json /srv/aware-care/infra/fury/
# #537: the model catalogue; the API takes another catalogue model's manifest from it by the served label.
COPY infra/models/catalog.json /srv/aware-care/infra/models/
USER 65532:65532
# #156: no access log. Request lines carry case, question and export IDs; nginx disables its access log for the same
# reason. Unhandled errors are logged content-free by the app (app/core/errors.py).
ENTRYPOINT ["uvicorn", "app.main:app", "--no-server-header", "--no-access-log"]
CMD ["--host", "127.0.0.1", "--port", "8000"]
