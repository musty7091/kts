# app/__init__.py
import os
import secrets
from datetime import datetime

from flask import Flask, abort, current_app, flash, redirect, request, session, url_for
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import inspect

from config import Config

# Eklenti nesnelerini global olarak tanımla
db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
csrf = CSRFProtect()


AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOGIN_PATHS = {"/admin/login", "/business/login", "/courier/login"}
PROTECTED_PREFIXES = ("/admin", "/business", "/courier")


def _client_ip() -> str:
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip() or "unknown"


def _is_prod_like(app: Flask) -> bool:
    return not (app.debug or app.testing)


def _audit_table_exists() -> bool:
    try:
        inspector = inspect(db.engine)
        return "audit_log" in inspector.get_table_names()
    except Exception:
        return False


def _build_csp(app: Flask) -> str:
    script_src = "'self' 'unsafe-inline' https://code.jquery.com https://cdn.jsdelivr.net https://stackpath.bootstrapcdn.com"
    style_src = "'self' 'unsafe-inline' https://stackpath.bootstrapcdn.com https://cdnjs.cloudflare.com https://fonts.googleapis.com"
    img_src = "'self' data: blob: https:"
    font_src = "'self' data: https://cdnjs.cloudflare.com https://fonts.gstatic.com"

    if app.debug or app.testing:
        script_src += " 'unsafe-eval'"
        connect_src = "'self' ws: wss: https:"
    else:
        connect_src = "'self' https:"

    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {script_src}",
            f"style-src {style_src}",
            f"img-src {img_src}",
            f"font-src {font_src}",
            f"connect-src {connect_src}",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
    )


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    if not app.config.get("SECRET_KEY"):
        raise ValueError(
            "Uygulama için bir SECRET_KEY ayarlanmalıdır! Lütfen config.py dosyasını kontrol edin."
        )

    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)

    # -------------------------
    # Reverse proxy düzeltmesi (HTTPS şeması / gerçek IP)
    # -------------------------
    use_proxyfix_env = os.environ.get("USE_PROXYFIX", "").strip().lower()
    prod_like = _is_prod_like(app)

    if use_proxyfix_env in ("1", "true", "yes", "on"):
        use_proxyfix = True
    elif use_proxyfix_env in ("0", "false", "no", "off"):
        use_proxyfix = False
    else:
        use_proxyfix = prod_like

    if use_proxyfix:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
            x_port=1,
            x_prefix=1,
        )

    # -------------------------
    # Login brute-force koruması (blok kontrolü)
    # -------------------------
    @app.before_request
    def _login_throttle_guard():
        if request.method != "POST":
            return None

        path = request.path or ""
        if path not in LOGIN_PATHS:
            return None

        from .models import LoginAttempt

        ip = _client_ip()
        attempt = LoginAttempt.query.filter_by(ip=ip, path=path).first()
        now = datetime.now()

        if attempt and attempt.blocked_until and now > attempt.blocked_until:
            try:
                db.session.delete(attempt)
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.warning("Login throttle kaydı temizlenemedi.", exc_info=app.debug)
            attempt = None

        if attempt and attempt.blocked_until and now < attempt.blocked_until:
            current_app.logger.warning("Login throttle BLOCK: ip=%s path=%s", ip, path)
            abort(429)

        return None

    @app.errorhandler(429)
    def _too_many_requests(e):
        return (
            "Çok fazla deneme yapıldı. Lütfen birkaç dakika sonra tekrar deneyin.",
            429,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    # -------------------------
    # RBAC (Admin / İşletme / Kurye) tek merkezden zorunlu kıl
    # -------------------------
    @app.before_request
    def _rbac_guard():
        bp = request.blueprint
        endpoint = request.endpoint

        if not bp:
            return None

        if bp == "static" or endpoint == "static":
            return None

        if endpoint in ("bp_admin.login", "bp_business.login", "bp_courier.login"):
            return None

        if bp == "bp_admin":
            if "admin_id" not in session:
                flash("Lütfen admin girişi yapın.", "warning")
                return redirect(url_for("bp_admin.login"))
            return None

        if bp == "bp_business":
            if "isletme_id" not in session:
                flash("Lütfen işletme girişi yapın.", "warning")
                return redirect(url_for("bp_business.login"))
            return None

        if bp == "bp_courier":
            if "kurye_id" not in session:
                flash("Lütfen kurye girişi yapın.", "warning")
                return redirect(url_for("bp_courier.login"))
            return None

        return None

    # -------------------------
    # Otomatik Audit Log (kritik istekler)
    # -------------------------
    @app.after_request
    def _audit_state_changing_requests(response):
        try:
            path = request.path or ""

            if not path.startswith(PROTECTED_PREFIXES):
                return response

            if request.method not in AUDITED_METHODS:
                return response

            if path in LOGIN_PATHS:
                return response

            # Audit tablosu migration ile oluşmadıysa uygulamayı kırma
            if not _audit_table_exists():
                return response

            actor_type = "system"
            actor_id = None
            if path.startswith("/admin") and "admin_id" in session:
                actor_type, actor_id = "admin", session.get("admin_id")
            elif path.startswith("/business") and "isletme_id" in session:
                actor_type, actor_id = "isletme", session.get("isletme_id")
            elif path.startswith("/courier") and "kurye_id" in session:
                actor_type, actor_id = "kurye", session.get("kurye_id")

            ip = _client_ip()
            ua = request.headers.get("User-Agent") or None
            action = f"{request.method} {request.endpoint or path}"
            details = {
                "path": path,
                "endpoint": request.endpoint,
                "status_code": int(getattr(response, "status_code", 0) or 0),
            }

            from .models import create_audit_log

            create_audit_log(
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                entity_type=None,
                entity_id=None,
                ip=ip,
                user_agent=ua,
                details=details,
            )
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            current_app.logger.warning(f"Audit log yazılamadı: {e}")
            if app.debug:
                current_app.logger.error(f"Audit log after_request hatası: {e}", exc_info=True)

        return response

    # -------------------------
    # Güvenlik header'ları
    # -------------------------
    @app.after_request
    def _set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(self), microphone=(), camera=()")
        response.headers.setdefault("Content-Security-Policy", _build_csp(app))

        if not prod_like:
            response.headers.setdefault("Cache-Control", "no-store")

        if prod_like:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        return response

    @app.context_processor
    def utility_processor():
        from .models import Bildirimler

        unread_notifications = []
        unread_count = 0
        view_all_notifications_url = None
        user_type = None

        try:
            if "admin_id" in session:
                user_id = session.get("admin_id")
                user_type = "admin"
                unread_notifications = (
                    Bildirimler.query.filter_by(admin_id=user_id, okundu_mu=False)
                    .order_by(Bildirimler.olusturulma_tarihi.desc())
                    .limit(5)
                    .all()
                )
                unread_count = Bildirimler.query.filter_by(admin_id=user_id, okundu_mu=False).count()
            elif "isletme_id" in session:
                user_id = session.get("isletme_id")
                user_type = "isletme"
                unread_notifications = (
                    Bildirimler.query.filter_by(isletme_id=user_id, okundu_mu=False)
                    .order_by(Bildirimler.olusturulma_tarihi.desc())
                    .limit(5)
                    .all()
                )
                unread_count = Bildirimler.query.filter_by(isletme_id=user_id, okundu_mu=False).count()
            elif "kurye_id" in session:
                user_id = session.get("kurye_id")
                user_type = "kurye"
                unread_notifications = (
                    Bildirimler.query.filter_by(kurye_id=user_id, okundu_mu=False)
                    .order_by(Bildirimler.olusturulma_tarihi.desc())
                    .limit(5)
                    .all()
                )
                unread_count = Bildirimler.query.filter_by(kurye_id=user_id, okundu_mu=False).count()

            if user_type:
                view_all_notifications_url = url_for("bp_common.view_all_notifications")

        except Exception as e:
            if app.debug:
                current_app.logger.error(f"Bildirim context processor hatası: {e}", exc_info=True)

        return dict(
            now=datetime.now,
            unread_notifications=unread_notifications,
            unread_notification_count=unread_count,
            view_all_notifications_url=view_all_notifications_url,
        )

    with app.app_context():
        from . import models

        @app.cli.command("create-tables")
        def create_tables_command():
            db.create_all()
            print("Veritabanı tabloları başarıyla oluşturuldu (veya zaten mevcuttu).")

        @app.cli.command("init-data")
        def init_data_command():
            print("Başlangıç verileri kontrol ediliyor/ekleniyor...")

            ayar_kargo_ucreti_adi = "sabit_kargo_hizmet_bedeli"
            sabit_kargo_ayari = models.Ayarlar.query.filter_by(ayar_adi=ayar_kargo_ucreti_adi).first()
            if not sabit_kargo_ayari:
                yeni_ayar_kargo = models.Ayarlar(
                    ayar_adi=ayar_kargo_ucreti_adi,
                    ayar_degeri="100.00",
                    aciklama="Kargo başına işletmeden alınacak standart hizmet bedeli (TL).",
                )
                db.session.add(yeni_ayar_kargo)
                print(f"- Varsayılan '{ayar_kargo_ucreti_adi}' ayarı (100.00 TL) eklendi.")
            else:
                print(f"- '{ayar_kargo_ucreti_adi}' ayarı zaten mevcut: {sabit_kargo_ayari.ayar_degeri} TL.")

            admin_kullanici_adi_str = os.environ.get("ADMIN_USER", "admin")
            admin_sifre_str = os.environ.get("ADMIN_PASS")
            admin_email_str = os.environ.get("ADMIN_EMAIL", "admin@example.com")

            if not admin_sifre_str:
                admin_sifre_str = secrets.token_urlsafe(16)
                print("!!! GÜVENLİK UYARISI: ADMIN_PASS ortam değişkeni bulunamadı.")
                print(f"!!! YENİ ÜRETİLEN GEÇİCİ ADMIN ŞİFRESİ: {admin_sifre_str}")
                print("!!! Lütfen bu şifreyi kaydedin ve giriş yaptıktan sonra değiştirin.")

            admin_kullanicisi = models.AdminKullanicilar.query.filter_by(kullanici_adi=admin_kullanici_adi_str).first()
            if not admin_kullanicisi:
                hashed_sifre = generate_password_hash(admin_sifre_str)
                yeni_admin = models.AdminKullanicilar(
                    kullanici_adi=admin_kullanici_adi_str,
                    sifre_hash=hashed_sifre,
                    email=admin_email_str,
                )
                db.session.add(yeni_admin)
                print(f"- '{admin_kullanici_adi_str}' adlı admin kullanıcısı oluşturuldu.")
            else:
                if admin_sifre_str and not check_password_hash(admin_kullanicisi.sifre_hash, admin_sifre_str):
                    admin_kullanicisi.sifre_hash = generate_password_hash(admin_sifre_str)
                    print(f"- '{admin_kullanici_adi_str}' adlı admin kullanıcısının şifresi güncellendi.")
                else:
                    print(f"- '{admin_kullanici_adi_str}' adlı admin kullanıcısı zaten mevcut.")

            kurye_kullanici_adi_str = os.environ.get("COURIER_USER", "").strip()
            kurye_sifre_str = os.environ.get("COURIER_PASS", "").strip()
            kurye_ad_soyad_str = os.environ.get("COURIER_NAME", "Ali Kurye").strip() or "Ali Kurye"
            kurye_telefon_str = os.environ.get("COURIER_PHONE", "05001234567").strip() or "05001234567"

            if kurye_kullanici_adi_str:
                kurye_kullanicisi_db = models.Kuryeler.query.filter_by(kullanici_adi=kurye_kullanici_adi_str).first()
                if not kurye_kullanicisi_db:
                    if not kurye_sifre_str:
                        kurye_sifre_str = secrets.token_urlsafe(16)
                        print("!!! GÜVENLİK UYARISI: COURIER_PASS ortam değişkeni bulunamadı.")
                        print(f"!!! YENİ ÜRETİLEN GEÇİCİ KURYE ŞİFRESİ: {kurye_sifre_str}")
                        print("!!! Lütfen bu şifreyi güvenli şekilde saklayın ve ilk giriş sonrası değiştirin.")

                    yeni_kurye_obj = models.Kuryeler(
                        kullanici_adi=kurye_kullanici_adi_str,
                        ad_soyad=kurye_ad_soyad_str,
                        telefon=kurye_telefon_str,
                        email=f"{kurye_kullanici_adi_str}@example.com",
                    )
                    yeni_kurye_obj.set_password(kurye_sifre_str)
                    db.session.add(yeni_kurye_obj)
                    print(f"- '{kurye_kullanici_adi_str}' adlı kurye oluşturuldu.")
                else:
                    print(f"- '{kurye_kullanici_adi_str}' adlı kurye zaten mevcut.")
            else:
                print("- COURIER_USER tanımlı değil; varsayılan kurye oluşturulmadı.")

            try:
                db.session.commit()
                print("Başlangıç verileri başarıyla işlendi.")
            except Exception as e:
                db.session.rollback()
                print(f"Başlangıç verileri kaydedilirken hata oluştu: {str(e)}")
                if app.debug:
                    current_app.logger.error(f"init-data commit hatası: {e}", exc_info=True)

        from .routes_admin import bp_admin
        app.register_blueprint(bp_admin)

        from .routes_business import bp_business
        app.register_blueprint(bp_business)

        from .routes_common import bp_common
        app.register_blueprint(bp_common)

        from .routes_courier import bp_courier
        app.register_blueprint(bp_courier)

    return app
