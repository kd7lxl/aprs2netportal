"""
Django settings for the aprs2netportal project.

All deployment-specific configuration comes from environment variables, see
.env.example for the full list. With no environment at all the project starts
in a development-friendly but locked-down state: SQLite database, console
email, DEBUG off.
"""
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name):
    return [v.strip() for v in os.environ.get(name, '').split(',') if v.strip()]


DEBUG = env_bool('DEBUG')

SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = 'insecure-development-key-do-not-use-in-production'
    else:
        raise ImproperlyConfigured(
            "The SECRET_KEY environment variable must be set when DEBUG is off.")

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

# Set when a TLS-terminating reverse proxy sits in front of the application
# and sets X-Forwarded-Proto on every request.
if env_bool('BEHIND_TLS_PROXY'):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Tell browsers to only ever use HTTPS for this host name. Deliberately
    # without includeSubDomains: the portal links to the status pages of the
    # Tier2 servers, http://<server>.aprs2.net:14501/, which have no TLS.
    SECURE_HSTS_SECONDS = int(os.environ.get('HSTS_SECONDS', 365 * 24 * 3600))

X_FRAME_OPTIONS = 'DENY'

# "manage.py check --deploy" suggestions that are deliberately not followed:
SILENCED_SYSTEM_CHECKS = [
    # HSTS includeSubDomains and preload: would break the plain HTTP status
    # page links to the Tier2 servers under aprs2.net, see above.
    'security.W005',
    'security.W021',
    # Redirecting HTTP to HTTPS is the reverse proxy's job; the application
    # is only ever spoken to over plain HTTP, by the proxy and by the
    # container health check.
    'security.W008',
]

# Everything the pages load comes from this site: no inline scripts or
# styles, no third-party hosts. Keep it that way (tests check the templates)
# rather than loosening this. data: images are used by Bootstrap's CSS for
# its icons (select arrow, validation marks, navbar toggler).
CONTENT_SECURITY_POLICY = {
    'default-src': ["'none'"],
    'script-src': ["'self'"],
    'style-src': ["'self'"],
    'img-src': ["'self'", 'data:'],
    'font-src': ["'self'"],
    'connect-src': ["'self'"],
    'form-action': ["'self'"],
    'frame-ancestors': ["'none'"],
    'base-uri': ["'none'"],
}

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',
    'sysop',
    'utils',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'utils.middleware.ContentSecurityPolicyMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# ARRL Logbook of The World client certificate login, for users that already
# exist; a certificate never creates one. The reverse proxy
# verifies the certificate and passes the result in request headers; see
# lotwauth/__init__.py and deploy/README.md. Never enable this unless the
# proxy overwrites these headers on every request.
LOTW_CLIENT_CERT_AUTH = env_bool('LOTW_CLIENT_CERT_AUTH')
LOTW_VERIFY_HEADER = 'HTTP_X_SSL_CLIENT_VERIFY'
LOTW_DN_HEADER = 'HTTP_X_SSL_CLIENT_S_DN'
if LOTW_CLIENT_CERT_AUTH:
    MIDDLEWARE.insert(
        MIDDLEWARE.index('django.contrib.auth.middleware.AuthenticationMiddleware') + 1,
        'lotwauth.middleware.LoTWCertificateMiddleware')
    AUTHENTICATION_BACKENDS.insert(0, 'lotwauth.backends.LoTWCertificateBackend')

ROOT_URLCONF = 'aprs2netportal.urls'
WSGI_APPLICATION = 'aprs2netportal.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

if os.environ.get('POSTGRES_HOST'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'HOST': os.environ['POSTGRES_HOST'],
            'PORT': os.environ.get('POSTGRES_PORT', ''),
            'NAME': os.environ.get('POSTGRES_DB', 'portal'),
            'USER': os.environ.get('POSTGRES_USER', 'portal'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# The existing production tables have 32-bit serial primary keys.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# The export views are cached and the cache is cleared when a record is saved.
# The cache must be shared between worker processes for that to work.
if os.environ.get('CACHE_DIR') and not TESTING:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
            'LOCATION': os.environ['CACHE_DIR'],
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

if TESTING:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'own_servers'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'assets']
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG or TESTING else
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

# Email: password reset messages and error reports to ADMINS.
if os.environ.get('EMAIL_HOST'):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.environ['EMAIL_HOST']
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '25'))
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'webmaster@localhost')
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)
ADMINS = [('Admin', address) for address in env_list('ADMINS')]
MANAGERS = ADMINS

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'formatters': {
        'plain': {
            'format': '%(asctime)s %(levelname)s %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'plain',
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.request': {
            'handlers': ['console', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
