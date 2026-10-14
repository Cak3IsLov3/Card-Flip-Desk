#!/bin/sh
# Apply migrations before the web server starts (only the web service sets
# RUN_MIGRATIONS=1, so one-off commands such as send_stale_digest skip this).
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
