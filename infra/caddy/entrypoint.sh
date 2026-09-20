#!/bin/sh
# Интернет-профиль отказывается стартовать с placeholder-доменом.
set -eu
addr="${DOORAIN_SITE_ADDRESS:-:80}"
case "$addr" in
  *example.com*|*example.org*|*your-domain*|*.example|"")
    echo "DOORAIN_SITE_ADDRESS содержит placeholder ('$addr'): укажите реальный домен в .env" >&2
    exit 1
    ;;
esac
exec "$@"
