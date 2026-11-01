import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env for developer convenience (DATABASE_URL, secrets, etc.).
# Real environment variables always take precedence (override=False), so this is
# effectively a no-op in production, where the platform injects the variables.
# python-dotenv is a dev convenience; guard the import so its absence is harmless.
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(BASE_DIR / '.env', override=False)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# OTA install tokens (and sessions/CSRF) are signed with this key, so it MUST
# be a strong secret in production — set DJANGO_SECRET_KEY on Railway. The
# committed default is a dev fallback only; if it is in use, signed tokens are
# forgeable by anyone with repo access.
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-dgmjrf7va0u11#qu4=a_yp=$+&#@%hsiyvgthiw+s++au^yh%5',
)

# SECURITY WARNING: don't run with debug turned on in production!
# Env-driven with a production-safe default (False). Set DJANGO_DEBUG=True for the
# local dev server. Parsing is explicit so DJANGO_DEBUG=False is honored
# (guards against the naive bool("False") == True pitfall).
DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('1', 'true', 'yes', 'on')

ALLOWED_HOSTS = [
    'beacon-innovation.com',
    'beaconinnovation-production.up.railway.app',
    'localhost',
    '127.0.0.1',
]

# CSRF trusted origins for secure form submissions
CSRF_TRUSTED_ORIGINS = [
    'https://beacon-innovation.com',
    'https://beaconinnovation-production.up.railway.app',
]

# Railway terminates TLS at its edge and forwards over http with this header.
# Without this, request.is_secure() is False behind the proxy. Apple OTA
# requires https end-to-end, so honoring the forwarded proto is important.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# --- Production security hardening ---------------------------------------------
# Mark session/CSRF cookies Secure in production. Guarded by DEBUG so the local
# (plain-http) dev server can still set them. Does not affect Beacon's public
# pages; applies to authenticated flows (WLJ/finance/products and /platform/).
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# HTTPS redirect — DEFERRED by default. Railway already serves HTTPS at the edge
# and forwards X-Forwarded-Proto (honored above). Turning on app-level redirect
# before the proxy + Railway healthcheck path are production-verified risks
# redirect loops / failed healthchecks. Env-gated so it can be enabled later
# WITHOUT a code change once verified: DJANGO_SECURE_SSL_REDIRECT=True.
SECURE_SSL_REDIRECT = os.environ.get(
    'DJANGO_SECURE_SSL_REDIRECT', 'False'
).lower() in ('1', 'true', 'yes', 'on')

# HSTS — DEFERRED (default 0 = off). HSTS is browser-cached and hard to walk back,
# so enable only after production HTTPS is confirmed stable. Env-gated: set
# DJANGO_SECURE_HSTS_SECONDS (e.g. 3600, then ramp to a year) to enable.
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'website',
    'wlj',
    'admin_console',
    'finance',
    'operations',
    'products',
    'distribution',
    # Enterprise Platform (incubated here; own DB + own /platform/ route).
    'aegis.core',
    'aegis.core_hr',
    'whitenoise.runserver_nostatic',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'distribution.middleware.LegacyRedirectMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Resolves platform tenant + platform user for /platform/ requests only.
    # Must run after AuthenticationMiddleware (BeaconSessionProvider reads
    # request.user). No-ops for all non-platform (Beacon) requests.
    'aegis.core.middleware.TenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
]

ROOT_URLCONF = 'beaconinnovation.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'beaconinnovation.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

# PostgreSQL is MANDATORY in every environment (local dev, automated tests, CI,
# staging, production). SQLite is no longer supported anywhere: there is no SQLite
# configuration and no fallback. Missing or non-PostgreSQL configuration fails
# loudly at startup rather than silently running on a disposable database.
# See docs/architecture/PHASE_0_DURABILITY.md.

def _require_postgres(url, var_name):
    """Parse a database URL and refuse anything that is not PostgreSQL."""
    config = dj_database_url.parse(url, conn_max_age=600)
    if 'postgresql' not in config.get('ENGINE', ''):
        raise ImproperlyConfigured(
            f"{var_name} must be a PostgreSQL connection URL "
            "(postgres://USER:PASSWORD@HOST:PORT/NAME); got engine "
            f"{config.get('ENGINE', '')!r}. SQLite is not supported in any "
            "environment."
        )
    return config


_DATABASE_URL = os.environ.get('DATABASE_URL')
if not _DATABASE_URL:
    raise ImproperlyConfigured(
        "DATABASE_URL is not set. Beacon requires a PostgreSQL database in every "
        "environment. For local development: `docker compose up -d` and copy "
        ".env.example to .env. See docs/architecture/PHASE_0_DURABILITY.md. "
        "SQLite is no longer supported."
    )

DATABASES = {
    # Beacon's primary database. PostgreSQL only.
    'default': _require_postgres(_DATABASE_URL, 'DATABASE_URL'),
}

# Enterprise Platform database (decision B1): a DEDICATED, SEPARATE PostgreSQL
# database, kept isolated from Beacon's `default` DB by the PlatformRouter below.
# It remains optional at the Beacon level — when PLATFORM_DATABASE_URL is unset the
# platform DB is simply absent and /platform/ fails closed (TenantMiddleware),
# leaving Beacon unaffected. This Phase 0 change does NOT merge the two databases.
PLATFORM_DATABASE_URL = os.environ.get('PLATFORM_DATABASE_URL')
if PLATFORM_DATABASE_URL:
    DATABASES['platform'] = _require_postgres(
        PLATFORM_DATABASE_URL, 'PLATFORM_DATABASE_URL'
    )

# The router is the enforced boundary between Beacon and the platform.
DATABASE_ROUTERS = ['aegis.core.routers.PlatformRouter']

# Enterprise Platform configuration. During single-tenant incubation the active
# tenant is resolved by this code; the mechanism is already multi-tenant.
PLATFORM_URL_PREFIX = '/platform/'
PLATFORM_TENANT_CODE = os.environ.get('PLATFORM_TENANT_CODE', 'BEACON')


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = ['static/']
STATICFILES_STOREAGE = 'whitenoise.storage.CompressedManifestStaticFileStorage'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Serve the iOS OTA manifest with the content type iTunes/iOS expects.
# (Python's mimetypes does not know .plist/.ipa, which otherwise fall back to
#  application/octet-stream and can make itms-services OTA installs unreliable.)
WHITENOISE_MIMETYPES = {
    '.plist': 'text/xml',
}

# Beacon distribution: release artifacts served at /downloads/<product>/ by the
# `distribution` app (written by the Beacon Release Engine, scripts/beacon_release).
DOWNLOADS_ROOT = BASE_DIR / 'downloads'

# Admin → Products: PRIVATE Developer Guide snapshots (per product, SHA-identified),
# deployed by each product's own pipeline. Served ONLY through the authenticated,
# staff-gated admin_console.product_views.developer_guide view — never via /static/
# (WhiteNoise) or /downloads/ (both public). Not in STATICFILES_DIRS.
DEVGUIDE_ROOT = BASE_DIR / 'product_guides'

# Media files (uploads — includes finance receipts and CSV imports).
#
# Receipts are sensitive financial documents. They are stored on a private
# FileField and served ONLY through access-checked Django views (never a public
# URL), so they must live on durable, private storage — NOT a public CDN. On
# Railway this means mounting a persistent Volume and pointing DJANGO_MEDIA_ROOT
# at its mount path; locally it defaults to BASE_DIR/media. Making the path an
# env var keeps existing file references intact (upload_to paths are unchanged)
# and preserves the existing access controls. Cloudinary is intentionally NOT used
# for receipts: its delivery URLs are unsuitable for sensitive records.
MEDIA_URL = '/media/'
MEDIA_ROOT = os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login settings
LOGIN_URL = 'wlj:login'

# Claude API Key for admin console task management
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', 'beacon-claude-api-key-replace-me-with-real-key')

# Cloudinary configuration (shared with WLJ)
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')

# Finance app settings
FINANCE_TAX_ALERT_THRESHOLD = int(os.environ.get('FINANCE_TAX_ALERT_THRESHOLD', '1000'))
FINANCE_RECEIPT_MAX_SIZE_MB = int(os.environ.get('FINANCE_RECEIPT_MAX_SIZE_MB', '10'))
FINANCE_CLOUDINARY_FOLDER = 'beacon-innovations/receipts'
FINANCE_ALLOWED_RECEIPT_TYPES = ['pdf', 'jpg', 'jpeg', 'png']
