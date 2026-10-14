"""
Django settings voor Card Flip Desk.

Gevoelige waarden komen uit omgevingsvariabelen; de defaults zijn alleen
bedoeld voor lokale ontwikkeling.
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
    "inventory",
    "finance",
    "sales",
    "ebay",
    "pricing",
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


LANGUAGE_CODE = "nl-nl"
TIME_ZONE = "Europe/Amsterdam"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Foto's staan buiten elke publieke map en worden alleen via een view met
# eigenaarscontrole uitgeleverd. Wissel naar S3-compatibele opslag door de
# "photos"-backend te vervangen; de modellen hoeven daarvoor niet te veranderen.
PRIVATE_MEDIA_ROOT = Path(os.environ.get("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "photos": {"BACKEND": "inventory.storage.PrivatePhotoStorage"},
}

PHOTO_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per bestand
PHOTO_MAX_INPUT_DIMENSION = 8000  # px; grotere bestanden worden geweigerd
PHOTO_MAX_DIMENSION = 1600  # px; langste zijde na verkleinen
PHOTO_THUMB_SIZE = 300  # px; langste zijde van de thumbnail
PHOTOS_PER_CARD = 6


# Voor links in e-mails (er is geen request om de host uit te halen).
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Card Flip Desk <noreply@localhost>")

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# eBay. Zonder EBAY_CLIENT_ID/SECRET werkt de app gewoon, alleen zonder
# actieve eBay-prijzen. Sleutels horen in omgevingsvariabelen, nooit in git.
EBAY_ENVIRONMENT = os.environ.get("EBAY_ENVIRONMENT", "sandbox")  # sandbox | production
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
EBAY_RUNAME = os.environ.get("EBAY_RUNAME", "")  # redirect_uri voor de Authorization Code Flow
EBAY_MARKETPLACE_ID = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_NL")
EBAY_CURRENCY = os.environ.get("EBAY_CURRENCY", "EUR")
EBAY_CATEGORY_IDS = os.environ.get("EBAY_CATEGORY_IDS", "")  # optioneel, bv. sportkaarten
EBAY_USER_SCOPES = os.environ.get(
    "EBAY_USER_SCOPES",
    "https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
).split()
EBAY_DAILY_CALL_BUDGET = int(os.environ.get("EBAY_DAILY_CALL_BUDGET", "4500"))  # eBay: 5000/dag
EBAY_CACHE_SECONDS = int(os.environ.get("EBAY_CACHE_SECONDS", str(6 * 3600)))

# Fernet-sleutel(s) voor tokens in de database, komma-gescheiden (de eerste
# versleutelt, de rest kan nog ontsleutelen: zo roteer je sleutels).
# Maak er een met: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEYS = [k for k in os.environ.get("TOKEN_ENCRYPTION_KEYS", "").split(",") if k]


REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
