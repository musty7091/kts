# config.py
import os
import secrets
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(16)

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'instance', 'kargo_sistemi.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ------------------------
    # Session / Cookie Güvenliği
    # ------------------------
    # Varsayılanlar geliştirme ortamına uygundur.
    # Prod ortamında (HTTPS) SESSION_COOKIE_SECURE=1 önerilir.
    SESSION_COOKIE_HTTPONLY = True

    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')

    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '').strip().lower() in ('1', 'true', 'yes', 'on')

    # Session süresi (dakika). Varsayılan 8 saat.
    _session_minutes = int(os.environ.get('SESSION_LIFETIME_MINUTES') or 480)
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=_session_minutes)
    # ------------------------

    # --- E-posta Ayarları ---
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', 'on', '1']

    # Sadece .env / environment üzerinden gelsin (hardcoded kaldırıldı)
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')

    MAIL_DEFAULT_SENDER_NAME = os.environ.get('MAIL_DEFAULT_SENDER_NAME', 'BeeCargo')
    MAIL_DEFAULT_SENDER_EMAIL = os.environ.get('MAIL_DEFAULT_SENDER_EMAIL', (MAIL_USERNAME or ''))
    MAIL_DEFAULT_SENDER = (MAIL_DEFAULT_SENDER_NAME, MAIL_DEFAULT_SENDER_EMAIL)
    # ------------------------

    SITE_NAME = os.environ.get('SITE_NAME') or 'BeeCargo'