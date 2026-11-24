"""
Django settings for the Afaq ERP project.

All secrets and environment-specific values come from the .env file
(see .env.example). Nothing secret is hard-coded here.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
COMPANY_NAME = env("COMPANY_NAME", default="AFAQ ALSIYANAH ALDAWLIYAH EST")
# Seller details printed on tax invoices and encoded in the ZATCA QR code.
# Replace the placeholders with the company's real registration data in .env.
COMPANY_NAME_AR = env("COMPANY_NAME_AR", default="مؤسسة آفاق الصيانة الدولية")
COMPANY_VAT_NUMBER = env("COMPANY_VAT_NUMBER", default="300000000000003")
COMPANY_CR_NUMBER = env("COMPANY_CR_NUMBER", default="")
COMPANY_ADDRESS = env("COMPANY_ADDRESS", default="Riyadh, Saudi Arabia")
INVOICE_PAYMENT_TERMS_DAYS = env.int("INVOICE_PAYMENT_TERMS_DAYS", default=30)
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "simple_history",
    # Local apps
    "core",
    "hr",
    "payroll",
    "expenses",
    "customers",
    "jobs",
    "invoicing",
    "security",
    "leave",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "security.middleware.IdleTimeoutMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
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
                "core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database (PostgreSQL only)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "security.validators.LettersAndDigitsValidator"},
]


# Internationalization (English + Arabic, Saudi time)

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("ar", "العربية"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = "Asia/Riyadh"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Uploaded files (receipts). Deliberately NOT served under a public URL;
# downloads go through permission-checked views.
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))


# Authentication

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
# Refuses locked-out usernames/IPs (security.services) on every login form, incl. admin.
AUTHENTICATION_BACKENDS = ["security.backends.LockoutModelBackend"]


# Sessions

SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 8 * 60 * 60                 # one working day at most
SESSION_COOKIE_HTTPONLY = True
SESSION_IDLE_MINUTES = env.int("SESSION_IDLE_MINUTES", default=30)   # security.middleware


# Security headers (always on)

X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True

# HTTPS: turn on in .env once the server has a certificate (Nginx terminates TLS).
HTTPS = env.bool("HTTPS", default=False)
SECURE_SSL_REDIRECT = HTTPS
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SECURE_HSTS_SECONDS = 31536000 if HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS
SECURE_HSTS_PRELOAD = HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if HTTPS else None
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS] if HTTPS else []

# A less guessable admin address keeps automated scanners away from the admin login.
ADMIN_URL = env("ADMIN_URL", default="admin/")


# Email: SMTP when EMAIL_HOST is set (production), console output otherwise.

# (A module-level EMAIL_HOST name is not allowed next to MAILERS in Django 6.1.)
_smtp_host = env("EMAIL_HOST", default="")
if _smtp_host:
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": _smtp_host,
                "port": env.int("EMAIL_PORT", default=587),
                "username": env("EMAIL_USER", default=""),
                "password": env("EMAIL_PASSWORD", default=""),
                "use_tls": env.bool("EMAIL_USE_TLS", default=True),
            },
        },
    }
else:
    MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}
