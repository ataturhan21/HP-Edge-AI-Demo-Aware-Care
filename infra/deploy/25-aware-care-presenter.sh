#!/bin/sh
# Enables the presenter API path /presenter-api/ of the one gateway (ADR-005 option A, amended by #487) when
# configured. Runs from the nginx image entrypoint after the gateway template is rendered. Always writes
# /tmp/aware-care/presenter-api.conf, which web.conf.template includes: the signing proxy when enabled, otherwise a
# refusal. Presenter access needs a loopback bind: without ADR-005's still-open TLS / mTLS control it must never reach
# a network (the deploy tool refuses such a configuration first; this is the second check).
set -eu
mkdir -p /tmp/aware-care
bind="${AWARECARE_WEB_BIND:-127.0.0.1}"
case "$bind" in
  127.0.0.1|localhost|::1|'[::1]') loopback=1 ;;
  *) loopback=0 ;;
esac
if [ "${AWARECARE_PRESENTER_ENABLED:-0}" = "1" ] && [ -r /run/secrets/presenter.key ] && [ "$loopback" = "1" ]; then
  # The single quotes are intended: envsubst takes a literal list of variables to substitute.
  # shellcheck disable=SC2016
  envsubst '${AWARECARE_API_PORT}' \
    < /etc/nginx/aware-care/presenter-api.conf.template > /tmp/aware-care/presenter-api.conf
  echo "aware-care: presenter path enabled at /presenter-api/ on ${bind}:${AWARECARE_WEB_PORT}"
else
  cp /etc/nginx/aware-care/presenter-api-disabled.conf /tmp/aware-care/presenter-api.conf
  if [ "${AWARECARE_PRESENTER_ENABLED:-0}" = "1" ] && [ "$loopback" != "1" ]; then
    echo "aware-care: presenter path disabled (refused: the gateway binds ${bind}, not loopback)"
  else
    echo "aware-care: presenter path disabled (not enabled or no readable key)"
  fi
fi
