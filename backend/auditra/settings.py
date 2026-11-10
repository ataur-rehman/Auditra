import os
import warnings
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# Local .env files are for the laptop setup only; on Railway every value comes from the service variables.
if not os.getenv('RAILWAY_ENVIRONMENT'):
    _load_env_file(BASE_DIR.parent / '.env')
    _load_env_file(BASE_DIR / '.env')


def _env_bool(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in ('1', 'true', 'yes')


def _env_list(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


DEV_SECRET_KEY = 'auditra-secret-key-2026-change-in-production'
DEV_INGEST_KEY = 'auditra-ingest-dev-key'

# On Railway (or any host that sets RAILWAY_ENVIRONMENT) DEBUG is off unless asked for explicitly.
DEBUG = _env_bool('DEBUG', not os.getenv('RAILWAY_ENVIRONMENT'))

SECRET_KEY = os.getenv('SECRET_KEY', DEV_SECRET_KEY if DEBUG else '')

ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS', '*' if DEBUG else '')
if os.getenv('RAILWAY_PUBLIC_DOMAIN'):
    ALLOWED_HOSTS.append(os.environ['RAILWAY_PUBLIC_DOMAIN'])
if os.getenv('RAILWAY_ENVIRONMENT'):
    # Railway's deploy health check calls /api/health/ with this Host header.
    ALLOWED_HOSTS.append('healthcheck.railway.app')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'compliance',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'auditra.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'auditra.wsgi.application'

if os.getenv('DATABASE_URL') and os.getenv('DB_ENGINE', 'postgresql') != 'sqlite':
    import dj_database_url

    DATABASES = {'default': dj_database_url.parse(os.environ['DATABASE_URL'], conn_max_age=600)}
elif os.getenv('DB_ENGINE', 'postgresql') == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.getenv('DB_NAME', str(BASE_DIR / 'db.sqlite3')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'auditra_db'),
            'USER': os.getenv('DB_USER', 'auditra_user'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'auditra123'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Karachi')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Before the first collectstatic (local runs, tests) the folder does not exist yet; that is expected.
warnings.filterwarnings('ignore', message='No directory at', module='whitenoise.base')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# The console on Vercel calls the API on Railway, so its origin must be listed here in production.
CORS_ALLOWED_ORIGINS = _env_list('CORS_ALLOWED_ORIGINS')
CORS_ALLOW_ALL_ORIGINS = _env_bool('CORS_ALLOW_ALL_ORIGINS', DEBUG and not CORS_ALLOWED_ORIGINS)
CSRF_TRUSTED_ORIGINS = _env_list('CSRF_TRUSTED_ORIGINS')
if os.getenv('RAILWAY_PUBLIC_DOMAIN'):
    CSRF_TRUSTED_ORIGINS.append(f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}")

# Railway and Vercel end TLS at their proxy and forward plain HTTP.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

AUTH_USER_MODEL = 'compliance.AuditraUser'

# Email notifications. Console output is the safe development default;
# set EMAIL_BACKEND to SMTP and provide the variables below in production.
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = os.getenv('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '15'))
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Auditra <noreply@auditra.local>')
COMPLIANCE_ALERT_RECIPIENTS = [
    email.strip()
    for email in os.getenv('COMPLIANCE_ALERT_RECIPIENTS', '').split(',')
    if email.strip()
]

# Shared secret for business systems (decisions API) and, when AGENT_KEY_ENROLMENT is on, for registering agents
# without an enrolment code. The dev default keeps a local presentation working without extra setup.
INGEST_API_KEY = os.getenv('INGEST_API_KEY', DEV_INGEST_KEY if DEBUG else '')

# Agents normally enrol with a one-time code issued to an employee. The shared key path is for the LAN demo.
AGENT_KEY_ENROLMENT = _env_bool('AGENT_KEY_ENROLMENT', DEBUG)
AGENT_INTERVAL_SECONDS = int(os.getenv('AGENT_INTERVAL_SECONDS', '3'))
AGENT_INVENTORY_MINUTES = int(os.getenv('AGENT_INVENTORY_MINUTES', '10'))
ENROLMENT_CODE_MINUTES = int(os.getenv('ENROLMENT_CODE_MINUTES', '30'))
AGENT_DOWNLOAD_URL = os.getenv(
    'AGENT_DOWNLOAD_URL', 'https://github.com/ataur-rehman/Auditra/releases/latest/download/AuditraAgent.exe'
)
MONITORING_NOTICE_VERSION = os.getenv('MONITORING_NOTICE_VERSION', '1')

# Production must not start with the development secrets.
if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    if not SECRET_KEY or SECRET_KEY == DEV_SECRET_KEY:
        raise ImproperlyConfigured('Set SECRET_KEY to a long random value when DEBUG is off.')
    if INGEST_API_KEY == DEV_INGEST_KEY:
        raise ImproperlyConfigured('INGEST_API_KEY must not be the development key when DEBUG is off.')
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured('Set ALLOWED_HOSTS (or deploy on Railway, which sets RAILWAY_PUBLIC_DOMAIN).')
