# Aware Care web package (M12; R34, R37). Built for linux/arm64 by
# .github/workflows/release.yml; the build context is the repository root.
# Stage 1 builds the React/Vite bundle (tsc + vite build). Stage 2 serves it
# with unprivileged nginx on loopback and proxies /api to the API on host
# loopback (host networking; see spec/decisions/ADR-010-delivery-workflow.md).
# Ports come from AWARECARE_WEB_PORT / AWARECARE_API_PORT at `docker run`.
ARG NODE_IMAGE=node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6

FROM ${NODE_IMAGE} AS build
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
# A04 bundles the synthetic sample records from the single fixture source.
COPY fixtures/records /src/fixtures/records
# #304: A06 rebuilds an issued question from the reviewed templates after a reload (pathway content, ADR-003).
COPY content/pathways/general-adult-4/questions.json /src/content/pathways/general-adult-4/questions.json
RUN npm run build

FROM ${NGINX_IMAGE}
ARG APP_COMMIT=unknown
LABEL org.opencontainers.image.title="aware-care-web" \
      org.opencontainers.image.source="<your-repo-url>" \
      org.opencontainers.image.revision="${APP_COMMIT}" \
      org.opencontainers.image.description="Aware Care web gateway. Synthetic demonstration; not for clinical use."
USER root
RUN rm -f /etc/nginx/conf.d/default.conf
USER 101
COPY infra/deploy/nginx.conf /etc/nginx/nginx.conf
COPY infra/deploy/web.conf.template /etc/nginx/templates/web.conf.template
# #487: the presenter API path of the same gateway (signing or refusing snippet, chosen at start).
COPY infra/deploy/presenter-api.conf.template infra/deploy/presenter-api-disabled.conf infra/deploy/presenter.js /etc/nginx/aware-care/
COPY --chmod=0755 infra/deploy/25-aware-care-presenter.sh /docker-entrypoint.d/25-aware-care-presenter.sh
COPY --from=build /src/apps/web/dist /usr/share/nginx/html
# The rendered server block goes to /tmp so the root filesystem can stay read-only.
# The device name defaults to the Nano; the deploy configuration sets it per device (ADR-018).
# #487: one port for both roles; the presenter path is off unless the deploy tool enables it (key mounted, loopback).
ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp \
    AWARECARE_WEB_BIND=127.0.0.1 \
    AWARECARE_WEB_PORT=8180 \
    AWARECARE_API_PORT=8100 \
    AWARECARE_DEVICE_NAME="HP ZGX Nano" \
    AWARECARE_DEVICE_SHORT_NAME="ZGX Nano" \
    AWARECARE_ORIGIN="" \
    AWARECARE_PRESENTER_ENABLED=0
