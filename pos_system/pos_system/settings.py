import os
from pathlib import Path

# ─── Core ─────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
SECRET_KEY = 'your-secret-key-here'
DEBUG      = True
ALLOWED_HOSTS = ['*']

TIME_ZONE = 'Asia/Manila'
USE_TZ    = True

# ─── CSRF ─────────────────────────────────────────────────────
CSRF_TRUSTED_ORIGINS = [
    'https://*.ngrok-free.dev',
    'https://*.ngrok-free.app',
]
CSRF_COOKIE_SECURE   = False  # Set True only when using HTTPS in production
CSRF_USE_SESSIONS    = False  # Keep False to use cookies
CSRF_COOKIE_HTTPONLY = False  # Must stay False so JS can read the CSRF token

# ─── Session ──────────────────────────────────────────────────
SESSION_COOKIE_NAME             = 'pos_session'  # Isolates POS session from admin platform
SESSION_COOKIE_AGE              = 43200          # 12 hours — fits a typical POS shift
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY         = True
SESSION_COOKIE_SAMESITE         = 'Lax'

# ─── Installed Apps ───────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
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
        ],
    },
}]

# ─── Database ─────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'pos_db',
        'USER': 'pos_user',
        'PASSWORD': 'C3ntral@143',
        'HOST': '192.168.1.25',
        'PORT': '5432',
    }
}
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

# ─── Crispy Forms ─────────────────────────────────────────────
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK          = 'bootstrap5'

# ─── Static & Media ───────────────────────────────────────────
STATIC_URL       = '/static/'
STATIC_ROOT      = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL        = '/media/'
MEDIA_ROOT       = BASE_DIR / 'media'

# ─── Auth Redirects ───────────────────────────────────────────
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ─── Misc ─────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

X_FRAME_OPTIONS = 'SAMEORIGIN'