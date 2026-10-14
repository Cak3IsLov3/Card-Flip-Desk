"""
Django settings for Card Flip Desk.

Sensitive values come from environment variables; the defaults are only
meant for local development.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h
]


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


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Photos live outside any public directory and are only served through a view
# that checks ownership. Switch to S3-compatible storage by replacing the
# "photos" backend; the models do not need to change.
PRIVATE_MEDIA_ROOT = Path(os.environ.get("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
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

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# eBay. Without EBAY_CLIENT_ID/SECRET the app works fine, just without active
# eBay prices. Keys belong in environment variables, never in git.
EBAY_ENVIRONMENT = os.environ.get("EBAY_ENVIRONMENT", "sandbox")  # sandbox | production
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
EBAY_RUNAME = os.environ.get("EBAY_RUNAME", "")  # redirect_uri for the Authorization Code Flow
EBAY_MARKETPLACE_ID = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_NL")
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
