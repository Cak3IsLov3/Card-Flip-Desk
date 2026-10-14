"""
Django settings for Card Flip Desk.

Sensitive values come from environment variables; the defaults are only
meant for local development.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name, default="0"):
    return os.environ.get(name, default) == "1"


def _env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def _database_from_url(url):
    """postgres://user:pass@host:5432/name or sqlite:///path/to/db.sqlite3"""
    parsed = urlparse(url)
    if parsed.scheme in ("postgres", "postgresql"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    if parsed.scheme == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": parsed.path.lstrip("/") or BASE_DIR / "db.sqlite3"}
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me",
)

DEBUG = _env_bool("DJANGO_DEBUG", "1")

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# Needed for forms when the site is reached via another origin, e.g. https://cards.example.com
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_htmx",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "inventory",
    "finance",
    "sales",
    "ebay",
    "pricing",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the collected static files in production (Docker), right after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# SQLite by default; set DATABASE_URL for PostgreSQL (Docker Compose does this).
DATABASES = {
    "default": _database_from_url(os.environ["DATABASE_URL"])
    if os.environ.get("DATABASE_URL")
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"


LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/Amsterdam"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Photos live outside any public directory and are only served through a view
# that checks ownership. Switch to S3-compatible storage by replacing the
# "photos" backend; the models do not need to change.
PRIVATE_MEDIA_ROOT = Path(os.environ.get("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Hashed, compressed file names in Docker (needs collectstatic); plain storage elsewhere.
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if _env_bool("DJANGO_STATIC_MANIFEST")
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
    "photos": {"BACKEND": "inventory.storage.PrivatePhotoStorage"},
}

PHOTO_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per file
PHOTO_MAX_INPUT_DIMENSION = 8000  # px; larger images are rejected
PHOTO_MAX_DIMENSION = 1600  # px; longest side after resizing
PHOTO_THUMB_SIZE = 300  # px; longest side of the thumbnail
PHOTOS_PER_CARD = 6


# For links in emails (there is no request to take the host from).
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Card Flip Desk <noreply@localhost>")

# SMTP when EMAIL_HOST is set; otherwise emails are printed to the console/log.
if os.environ.get("EMAIL_HOST"):
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": os.environ["EMAIL_HOST"],
                "port": int(os.environ.get("EMAIL_PORT", "587")),
                "username": os.environ.get("EMAIL_HOST_USER", ""),
                "password": os.environ.get("EMAIL_HOST_PASSWORD", ""),
                "use_tls": _env_bool("EMAIL_USE_TLS", "1"),
            },
        },
    }
else:
    MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}


# eBay. Without EBAY_CLIENT_ID/SECRET the app works fine, just without active
# eBay prices. Keys belong in environment variables, never in git.
EBAY_ENVIRONMENT = os.environ.get("EBAY_ENVIRONMENT", "sandbox")  # sandbox | production
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
EBAY_RUNAME = os.environ.get("EBAY_RUNAME", "")  # redirect_uri for the Authorization Code Flow
EBAY_MARKETPLACE_ID = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_DE")
EBAY_CURRENCY = os.environ.get("EBAY_CURRENCY", "EUR")
EBAY_CATEGORY_IDS = os.environ.get("EBAY_CATEGORY_IDS", "")  # optional, e.g. sports trading cards
EBAY_USER_SCOPES = os.environ.get(
    "EBAY_USER_SCOPES",
    "https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
).split()
EBAY_DAILY_CALL_BUDGET = int(os.environ.get("EBAY_DAILY_CALL_BUDGET", "4500"))  # eBay allows 5000/day
EBAY_CACHE_SECONDS = int(os.environ.get("EBAY_CACHE_SECONDS", str(6 * 3600)))

# Fernet key(s) for tokens stored in the database, comma-separated (the first
# one encrypts, the others can still decrypt: that is how you rotate keys).
# Create one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEYS = [k for k in os.environ.get("TOKEN_ENCRYPTION_KEYS", "").split(",") if k]


# Production hardening. Set DJANGO_HTTPS=1 when the site runs behind a TLS proxy.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if _env_bool("DJANGO_HTTPS"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    # Start low; raise once HTTPS is known to work everywhere (HSTS is hard to undo).
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
# Health checks come from inside the container over plain HTTP.
SECURE_REDIRECT_EXEMPT = [r"^health/$"]

# Log to stdout, so `docker compose logs` shows errors.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",  # for the docs in the browser
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "2000/hour", "token": "10/minute"},
    # Amounts as strings in JSON: no float rounding on the client side.
    "COERCE_DECIMAL_TO_STRING": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Card Flip Desk API",
    "DESCRIPTION": (
        "Inventory, photos, listings, sales and the fee calculator. "
        "Authenticate with `Authorization: Token <token>`; you can only see and change your own data. "
        "Amounts are decimal strings in euros."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}
