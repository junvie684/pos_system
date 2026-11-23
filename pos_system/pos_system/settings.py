import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP


def env_bool(name, default=False):
    return os.environ.get(name, '1' if default else '0').strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name):
    return [v.strip() for v in os.environ.get(name, '').split(',') if v.strip()]


# ─── Core ─────────────────────────────────────────────────────
# Production is the default. For local development put DJANGO_DEBUG=1 in a
# `.env` file next to manage.py (git-ignored, so it never reaches the server).
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Minimal KEY=VALUE loader. Real environment variables always win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / '.env')

TESTING  = len(sys.argv) > 1 and sys.argv[1] == 'test'
DEBUG    = env_bool('DJANGO_DEBUG')

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = 'django-insecure-dev-only-never-use-in-production'
    else:
        raise ImproperlyConfigured('Set the DJANGO_SECRET_KEY environment variable.')

RAILWAY_DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS')
if RAILWAY_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_DOMAIN)
if DEBUG:
    ALLOWED_HOSTS += ['localhost', '127.0.0.1', '[::1]', '.ngrok-free.dev', '.ngrok-free.app']

TIME_ZONE = 'Asia/Manila'
USE_TZ    = True

# ─── CSRF ─────────────────────────────────────────────────────
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')
if RAILWAY_DOMAIN:
    CSRF_TRUSTED_ORIGINS.append(f'https://{RAILWAY_DOMAIN}')
if DEBUG:
    CSRF_TRUSTED_ORIGINS += ['https://*.ngrok-free.dev', 'https://*.ngrok-free.app']
CSRF_USE_SESSIONS    = False  # Keep False to use cookies
CSRF_COOKIE_HTTPONLY = False  # Must stay False so JS can read the CSRF token

# ─── Session ──────────────────────────────────────────────────
SESSION_COOKIE_NAME             = 'pos_session'  # Isolates POS session from admin platform
SESSION_COOKIE_AGE              = 43200          # 12 hours — fits a typical POS shift
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY         = True
SESSION_COOKIE_SAMESITE         = 'Lax'

# ─── HTTPS / security headers (production only) ───────────────
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE    = True
    # Railway (and most PaaS) terminate TLS at a proxy and forward this header.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT     = env_bool('DJANGO_SECURE_SSL_REDIRECT', default=not TESTING)
    SECURE_HSTS_SECONDS     = int(os.environ.get('DJANGO_HSTS_SECONDS', 60 * 60 * 24 * 30))
    # Turn on only when every subdomain of the site's domain serves HTTPS.
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_HSTS_INCLUDE_SUBDOMAINS')
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY      = 'same-origin'

# ─── Installed Apps ───────────────────────────────────────────
INSTALLED_APPS = [
    'tenants.admin_site.PlatformAdminConfig',  # Django admin, platform admins only
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'crispy_forms',
    'crispy_bootstrap5',
    'products',
    'sales',
    'customers',
    'reports',
    'accounts',
    'price_checker',
    'tenants',
]

# ─── Middleware ────────────────────────────────────────────────
# AuthenticationMiddleware must come BEFORE TenantMiddleware
# so request.user is populated when tenant resolution runs.
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.csp.ContentSecurityPolicyMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # ← before TenantMiddleware
    'tenants.middleware.TenantMiddleware',                       # ← moved after auth
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ─── URLs & Templates ─────────────────────────────────────────
ROOT_URLCONF = 'pos_system.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
            'tenants.context_processors.current_tenant',
        ],
    },
}]

# ─── Database ─────────────────────────────────────────────────
# Production: DATABASE_URL=postgres://user:pass@host:5432/dbname (Railway sets
# this when you attach a PostgreSQL service). SQLite is for local development;
# on Railway the container disk is wiped on every deploy.
def _database_from_url(url):
    parts = urlparse(url)
    if parts.scheme not in ('postgres', 'postgresql'):
        raise ImproperlyConfigured(f'Unsupported DATABASE_URL scheme: {parts.scheme}')
    return {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     unquote(parts.path.lstrip('/')),
        'USER':     unquote(parts.username or ''),
        'PASSWORD': unquote(parts.password or ''),
        'HOST':     parts.hostname or '',
        'PORT':     str(parts.port or ''),
        'CONN_MAX_AGE': 60,
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS':  dict(parse_qsl(parts.query)),
    }


if os.environ.get('DATABASE_URL'):
    DATABASES = {'default': _database_from_url(os.environ['DATABASE_URL'])}
elif DEBUG or TESTING or env_bool('DJANGO_ALLOW_SQLITE'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
else:
    raise ImproperlyConfigured(
        'Set DATABASE_URL for production (or DJANGO_ALLOW_SQLITE=1 to knowingly run on SQLite).'
    )

# ─── Crispy Forms ─────────────────────────────────────────────
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK          = 'bootstrap5'

# ─── Static & Media ───────────────────────────────────────────
STATIC_URL       = '/static/'
STATIC_ROOT      = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL        = '/media/'
MEDIA_ROOT       = BASE_DIR / 'media'

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        # Hashed + compressed files need `collectstatic`; skip that in dev/tests.
        'BACKEND': ('django.contrib.staticfiles.storage.StaticFilesStorage' if (DEBUG or TESTING)
                    else 'whitenoise.storage.CompressedManifestStaticFilesStorage'),
    },
}

# ─── Passwords & sign-in ──────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
# accounts/throttle.py: lock a username after this many failed sign-ins.
LOGIN_FAILURE_LIMIT    = 5
LOGIN_LOCKOUT_SECONDS  = 15 * 60

# The sign-in throttle keeps its counts in the cache, so every gunicorn worker
# must see the same cache: production uses a database table (created by
# `manage.py createcachetable` in the Procfile). Dev and tests use memory.
if DEBUG or TESTING:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
                          'LOCATION': 'django_cache'}}

# ─── Auth Redirects ───────────────────────────────────────────
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ─── Misc ─────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

X_FRAME_OPTIONS = 'SAMEORIGIN'  # receipt opens in a same-origin modal frame

# Content-Security-Policy (all environments, so problems show up in dev).
# Everything the pages load is served by this site: fonts and icons are local.
# Templates still use inline <script>/<style> blocks and onclick handlers, so
# scripts and styles allow 'unsafe-inline'; moving those to static files would
# let this drop to 'self' only. The rest blocks plugins, foreign hosts, <base>
# hijacking, form posts to other sites and framing by other sites.
SECURE_CSP = {
    'default-src':     [CSP.SELF],
    'script-src':      [CSP.SELF, CSP.UNSAFE_INLINE],
    'style-src':       [CSP.SELF, CSP.UNSAFE_INLINE],
    'img-src':         [CSP.SELF, 'data:', 'blob:'],
    'font-src':        [CSP.SELF, 'data:'],
    'connect-src':     [CSP.SELF],
    'frame-src':       [CSP.SELF],
    'frame-ancestors': [CSP.SELF],
    'object-src':      [CSP.NONE],
    'base-uri':        [CSP.SELF],
    'form-action':     [CSP.SELF],
}
