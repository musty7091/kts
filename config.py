# config.py
import os
import secrets
from datetime import timedelta

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
    # Eğer dışarıdan bir anahtar verilmezse, çökmemesi için varsayılan bir anahtar belirledik.
    _secret = _env_str("SECRET_KEY", "beecargo_sabit_gizli_anahtar_2026_xyz")
    if _secret:
        SECRET_KEY = _secret
    else:
        # Dev/Test'te kolaylık: otomatik üret
        if TESTING or DEBUG or FLASK_ENV in ("development", "dev", "testing"):
            SECRET_KEY = secrets.token_hex(32)
        else:
            # Prod/SaaS için: zorunlu
            raise RuntimeError(
                "SECRET_KEY ortam değişkeni PROD ortamında zorunludur. "
                "Örn: export SECRET_KEY='uzun-rastgele-bir-deger'"
            )

    # ------------------------
    # DB
    # ------------------------
    _db_url = _normalize_db_url(_env_str("DATABASE_URL", ""))
    if _db_url:
        SQLALCHEMY_DATABASE_URI = _db_url
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "instance", "kargo_sistemi.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Kopan bağlantılarda daha az hata (özellikle Postgres)
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True
    }

    # ------------------------
    # Session / Cookie Güvenliği
    # ------------------------
    # Prod varsayılanı: HTTPS kabul edip secure cookie'yi true yap
    _is_prod_like = not (TESTING or DEBUG or FLASK_ENV in ("development", "dev", "testing"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = _env_str("SESSION_COOKIE_SAMESITE", "Lax")

    # Env ile override edilebilir; verilmezse prod-like ortamda True
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", _is_prod_like)

    # Session süresi (dakika). Varsayılan 8 saat.
    _session_minutes = int(_env_str("SESSION_LIFETIME_MINUTES", "480"))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=_session_minutes)

    # URL üretiminde prod'da https tercih edilsin (özellikle linkler / redirectler)
    PREFERRED_URL_SCHEME = _env_str("PREFERRED_URL_SCHEME", "https" if _is_prod_like else "http")

    # ------------------------
    # CSRF
    # ------------------------
    # Token'ı sonsuza kadar geçerli bırakmayalım (P0 hygiene)
    WTF_CSRF_TIME_LIMIT = int(_env_str("WTF_CSRF_TIME_LIMIT", "3600"))  # saniye (1 saat)

    # ------------------------
    # E-posta Ayarları
    # ------------------------
    MAIL_SERVER = _env_str("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(_env_str("MAIL_PORT", "587"))
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)

    # Sadece .env / environment üzerinden gelsin
    MAIL_USERNAME = _env_str("MAIL_USERNAME", "")
    MAIL_PASSWORD = _env_str("MAIL_PASSWORD", "")

    MAIL_DEFAULT_SENDER_NAME = _env_str("MAIL_DEFAULT_SENDER_NAME", "BeeCargo")
    MAIL_DEFAULT_SENDER_EMAIL = _env_str("MAIL_DEFAULT_SENDER_EMAIL", MAIL_USERNAME or "")
    MAIL_DEFAULT_SENDER = (MAIL_DEFAULT_SENDER_NAME, MAIL_DEFAULT_SENDER_EMAIL)

    SITE_NAME = _env_str("SITE_NAME", "BeeCargo")