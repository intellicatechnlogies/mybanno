import os
import base64
import hashlib
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-development-secret")
CREDENTIAL_API_KEY = os.environ.get(
    "CREDENTIAL_API_KEY",
    "mybanno-default-api-key-change-in-production",
)
CREDENTIAL_ENCRYPTION_KEY = os.environ.get(
    "CREDENTIAL_ENCRYPTION_KEY",
    base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode(),
)
DEBUG = False
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "store.apps.StoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "store.middleware.AdminIdleTimeoutMiddleware",
]

ROOT_URLCONF = "cloths_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "store.context_processors.site_options",
            ],
        },
    },
]

WSGI_APPLICATION = "cloths_project.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.environ.get("DJANGO_DB_PATH", BASE_DIR / "store.db")),
    }
}
PRODUCT_NAME_CATALOG_PATH = Path(
    os.environ.get("PRODUCT_NAME_CATALOG_PATH", BASE_DIR / ".product-name-catalog.json")
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = False

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024 + 64 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
