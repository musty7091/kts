# config.py
import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv  # .env dosyasındaki verileri okumak için eklendi

# .env dosyasındaki değişkenleri sisteme (os.environ) yükler
load_dotenv() 

basedir = os.path.abspath(os.path.dirname(__file__))


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else str(v).strip()


def _normalize_db_url(url: str) -> str:
    """
    Bazı ortamlarda DATABASE_URL 'postgres://' ile gelebilir.
    SQLAlchemy için 'postgresql://' olmalı.
    """
    if not url:
        return url
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql://" + u[len("postgres://") :]
    return u


class Config:
    # Ortam bilgisi
    FLASK_ENV = _env_str("FLASK_ENV", "production").lower()
    DEBUG = _env_bool("FLASK_DEBUG", False)
    TESTING = _env_bool("TESTING", False)

    # ------------------------
    # SECRET_KEY (P0 - kritik)
    # ------------------------
    _is_prod_like = not (TESTING or DEBUG or FLASK_ENV in ("development", "dev", "testing"))
    _secret_from_env = os.environ.get("SECRET_KEY")

    if _secret_from_env:
        SECRET_KEY = _secret_from_env
    else:
        if _is_prod_like:
            raise RuntimeError(
                "KRİTİK GÜVENLİK RİSKİ: SECRET_KEY ortam değişkeni PRODUCTION ortamında zorunludur! "
                "Lütfen sunucu ayarlarından SECRET_KEY tanımlayın."
            )
        else:
            SECRET_KEY = "beecargo_yerel_gelistirme_anahtari_2026_xyz"

    # ------------------------
    # DB (DATABASE_URL boşsa otomatik SQLite kullanılır)
    # ------------------------
    _db_url = _normalize_db_url(_env_str("DATABASE_URL", ""))
    if _db_url:
        SQLALCHEMY_DATABASE_URI = _db_url
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "instance", "kargo_sistemi.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True
    }

    # ------------------------
    # Session / Cookie Güvenliği
    # ------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = _env_str("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", _is_prod_like)

    _session_minutes = int(_env_str("SESSION_LIFETIME_MINUTES", "480"))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=_session_minutes)

    PREFERRED_URL_SCHEME = _env_str("PREFERRED_URL_SCHEME", "https" if _is_prod_like else "http")

    # ------------------------
    # CSRF
    # ------------------------
    WTF_CSRF_TIME_LIMIT = int(_env_str("WTF_CSRF_TIME_LIMIT", "3600"))

    # ------------------------
    # E-posta Ayarları (Bilgileri .env dosyasından okur)
    # ------------------------
    MAIL_SERVER = _env_str("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(_env_str("MAIL_PORT", "587"))
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)

    MAIL_USERNAME = _env_str("MAIL_USERNAME", "")
    MAIL_PASSWORD = _env_str("MAIL_PASSWORD", "")

    MAIL_DEFAULT_SENDER_NAME = _env_str("MAIL_DEFAULT_SENDER_NAME", "BeeCargo")
    MAIL_DEFAULT_SENDER_EMAIL = _env_str("MAIL_DEFAULT_SENDER_EMAIL", MAIL_USERNAME or "")
    MAIL_DEFAULT_SENDER = (MAIL_DEFAULT_SENDER_NAME, MAIL_DEFAULT_SENDER_EMAIL)

    SITE_NAME = _env_str("SITE_NAME", "BeeCargo")
    
    UPLOAD_FOLDER = os.path.join(basedir, 'app', 'static', 'uploads')