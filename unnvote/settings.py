"""Django settings for the UNN SUG facial recognition e-voting site.

Configuration comes from environment variables so the same code runs on a
laptop (SQLite) and on a server (MySQL). See README.md.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


DEV_SECRET_KEY = "dev-only-insecure-key-change-me"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", True)
if not DEBUG and SECRET_KEY == DEV_SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a long random value when DJANGO_DEBUG is false.")
# In development (DEBUG), also accept a Cloudflare quick tunnel, which is how phones
# reach the laptop over https in a practice run. Production sets both variables.
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" + (",.trycloudflare.com" if DEBUG else "")
).split(",")
CSRF_TRUSTED_ORIGINS = [
    o
    for o in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS", "https://*.trycloudflare.com" if DEBUG else ""
    ).split(",")
    if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "voting",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves /static/ when DEBUG is off and no web server sits in front (the laptop defence kit).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "unnvote.urls"

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

WSGI_APPLICATION = "unnvote.wsgi.application"

# MySQL when MYSQL_DATABASE is set (production), SQLite otherwise (development).
if os.environ.get("MYSQL_DATABASE"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ["MYSQL_DATABASE"],
            "USER": os.environ.get("MYSQL_USER", "root"),
            "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
            "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.environ.get("MYSQL_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
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

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "staff_login"
LOGIN_REDIRECT_URL = "staff_dashboard"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
if not DEBUG:
    # In production the app listens only on 127.0.0.1 behind Caddy, which handles
    # HTTPS and says so in this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_REFERRER_POLICY = "same-origin"

# Face verification. InsightFace ArcFace (buffalo_l w600k_r50) on faces found and
# aligned by OpenCV's YuNet; cosine distance, lower = more alike. On DeepFace's
# labelled test photos the closest two different people scored 0.80 and the same
# person at most 0.49 (Facenet512, the previous model: 0.48 and 0.42).
# The recognition model (174 MB) downloads to FACE_MODEL_DIR on first use.
FACE_MODEL_DIR = Path(os.environ.get("FACE_MODEL_DIR", Path.home() / ".unnvote" / "models"))
# Max distance to accept a face. Same-person photos years apart reach 0.49; a live
# scan against a fresh 3-photo registration is normally far below that.
FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.45"))
# A face must also be clearly closer to the claimed voter than to anyone else
# registered: if another voter's face is within this margin, the scan is refused
# as too close to call (e.g. siblings), rather than guessed.
FACE_MATCH_MARGIN = float(os.environ.get("FACE_MATCH_MARGIN", "0.10"))
# Threshold for refusing a registration because the face already belongs to
# another registered voter (one person, one registration). It equals the match
# threshold: a face is a duplicate exactly when it would pass as that voter on
# election day.
FACE_DUPLICATE_THRESHOLD = float(os.environ.get("FACE_DUPLICATE_THRESHOLD", str(FACE_MATCH_THRESHOLD)))
# Registration takes several photos and stores their average. If any two differ by
# more than this (blur, movement, a face half out of view), the registration is
# refused so no student is stored with a weak face record.
FACE_ENROL_CONSISTENCY = float(os.environ.get("FACE_ENROL_CONSISTENCY", "0.25"))
# Faces smaller than this (pixels, eye to chin roughly) are too far from the camera to trust.
FACE_MIN_SIZE = int(os.environ.get("FACE_MIN_SIZE", "80"))
# DeepFace's anti-spoofing (liveness) check: rejects photos and screens held up to
# the camera. Runs on TensorFlow. Set to false only for local debugging.
FACE_ANTI_SPOOFING = env_bool("FACE_ANTI_SPOOFING", True)
# How long a voter stays verified between the face scan and submitting the ballot.
VOTE_SESSION_MINUTES = int(os.environ.get("VOTE_SESSION_MINUTES", "10"))

# Print face scan timings (voting.faces) in the server console.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"voting": {"handlers": ["console"], "level": "INFO"}},
}
