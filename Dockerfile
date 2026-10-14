# syntax=docker/dockerfile:1
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 app

# Dependencies first, so code changes do not reinstall everything.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV DJANGO_DEBUG=0 \
    DJANGO_STATIC_MANIFEST=1 \
    DJANGO_STATIC_ROOT=/app/staticfiles \
    PRIVATE_MEDIA_ROOT=/data/private_media

# Static files are collected at build time; the secret is only a placeholder for this step.
RUN DJANGO_SECRET_KEY=build-only-not-secret python manage.py collectstatic --noinput \
    && mkdir -p /data/private_media \
    && chown -R app:app /data

USER app
EXPOSE 8000

ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
