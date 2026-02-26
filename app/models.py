# app/models.py
from . import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import enum # enum modülünü import et
import json

# Kargo Durumları için Enum Tanımlaması
class KargoDurumEnum(enum.Enum):
    HAZIRLANIYOR = "Hazırlanıyor"
    PAKETLENDI = "Paketlendi"
    KURYE_TESLIM_HAZIR = "Kuryeye Teslim Edilmeye Hazır"
    MUSTERIDEN_ALINMAYI_BEKLIYOR = "Müşteriden Alınmayı Bekliyor"
    KARGO_ALINDI_MERKEZDE = "Kargo Alındı (Merkezde)"
    DAGITIMDA = "Dağıtımda"
    TESLIM_EDILDI = "Teslim Edildi"
    TESLIM_EDILEMEDI_ALICI_ULASILAMADI = "Teslim Edilemedi (Alıcıya Ulaşılamadı)"
    TESLIM_EDILEMEDI_ADRES_HATALI = "Teslim Edilemedi (Adres Hatalı/Yetersiz)"
    IADE_SURECINDE = "İade Sürecinde (Merkeze Dönüyor)"
    IADE_EDILDI_ISLETMEYE = "İade Edildi (İşletmeye Teslim)"
    IPTAL_EDILDI_ISLETME = "İptal Edildi (İşletme Tarafından)"
    IPTAL_EDILDI_ADMIN = "İptal Edildi (Admin Tarafından)"

    # Şablonda doğrudan Enum üyesinin değerini (string) kullanmak için
    def __str__(self):
        return self.value

class Ayarlar(db.Model):
    __tablename__ = 'ayarlar'
    id = db.Column(db.Integer, primary_key=True)
    ayar_adi = db.Column(db.String(100), unique=True, nullable=False)
    ayar_degeri = db.Column(db.String(255), nullable=False)
    aciklama = db.Column(db.Text, nullable=True)
    guncellenme_tarihi = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f'<Ayar {self.ayar_adi}: {self.ayar_degeri}>'

class Isletmeler(db.Model):
    __tablename__ = 'isletmeler'
    id = db.Column(db.Integer, primary_key=True)
    isletme_adi = db.Column(db.String(200), nullable=False)
    yetkili_kisi = db.Column(db.String(150), nullable=True)
    isletme_telefon = db.Column(db.String(20), nullable=False) # GÜNCELLENDİ: nullable=False
    isletme_email = db.Column(db.String(120), unique=True, nullable=False)
    isletme_adres = db.Column(db.Text, nullable=True)
    kullanici_adi = db.Column(db.String(80), unique=True, nullable=False)
    sifre_hash = db.Column(db.String(255), nullable=False)
    isletme_kodu = db.Column(db.String(10), unique=True, nullable=False)
    son_kargo_no = db.Column(db.Integer, default=0)
    aktif_mi = db.Column(db.Boolean, default=True)
    olusturulma_tarihi = db.Column(db.DateTime, default=datetime.now)
    guncellenme_tarihi = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    kargolar = db.relationship('Kargolar', backref='isletme', lazy='dynamic')
    odemeler = db.relationship('IsletmeOdemeleri', backref='isletme', lazy='dynamic')
    bildirimler = db.relationship('Bildirimler', backref='isletme_bildirimleri', lazy='dynamic', foreign_keys='Bildirimler.isletme_id')

    def __repr__(self):
        return f'<İşletme {self.isletme_adi} ({self.isletme_kodu})>'

    def set_password(self, password):
        self.sifre_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.sifre_hash, password)

class Kargolar(db.Model):
    __tablename__ = 'kargolar'
    id = db.Column(db.Integer, primary_key=True)
    isletme_id = db.Column(db.Integer, db.ForeignKey('isletmeler.id'), nullable=False)
    takip_numarasi = db.Column(db.String(50), unique=True, nullable=False)
    alici_adi_soyadi = db.Column(db.String(150), nullable=False)
    alici_telefon = db.Column(db.String(20), nullable=False) # Bu zaten zorunlu
    alici_email = db.Column(db.String(120), nullable=True)
    alici_adres = db.Column(db.Text, nullable=False)
    alici_sehir = db.Column(db.String(100), nullable=False) # KKTC için bu "İlçe" olacak
    alici_ilce = db.Column(db.String(100), nullable=True)  # KKTC için bu "Köy/Mahalle" olacak
    urun_bedeli_alici_tahsil = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    kargo_ucreti_isletme_borcu = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    kargo_ucreti_alici_tahsil = db.Column(db.Numeric(10, 2), default=0.00)
    toplam_tahsil_edilecek_alici = db.Column(db.Numeric(10, 2), default=0.00)
    isletmeye_aktarilacak_tutar = db.Column(db.Numeric(10, 2), default=0.00)
    odeme_yontemi_teslimde = db.Column(db.String(50), nullable=True)
    odeme_durumu_alici = db.Column(db.String(50), nullable=False, default="Alıcıdan Ödeme Bekleniyor")
    
    kargo_durumu = db.Column(db.Enum(KargoDurumEnum), 
                             nullable=False, 
                             default=KargoDurumEnum.HAZIRLANIYOR) 
    
    ozel_not = db.Column(db.Text, nullable=True)
    planlanan_teslim_tarihi = db.Column(db.Date, nullable=True)
    teslim_tarihi = db.Column(db.DateTime, nullable=True)
    pdf_yolu = db.Column(db.String(255), nullable=True)
    isletmeye_aktarildi_mi = db.Column(db.Boolean, default=False)
    olusturulma_tarihi = db.Column(db.DateTime, default=datetime.now)
    guncellenme_tarihi = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    kurye_id = db.Column(db.Integer, db.ForeignKey('kuryeler.id'), nullable=True)
    
    alici_gecici_enlem = db.Column(db.Float, nullable=True)
    alici_gecici_boylam = db.Column(db.Float, nullable=True)
    alici_gecici_konum_zamani = db.Column(db.DateTime, nullable=True)

    odeme_iliskileri = db.relationship('OdemeKargoIliskileri', backref='kargo', lazy='dynamic')

    def __repr__(self):
        return f'<Kargo {self.takip_numarasi}>'

class Kuryeler(db.Model):
    __tablename__ = 'kuryeler'
    id = db.Column(db.Integer, primary_key=True)
    ad_soyad = db.Column(db.String(150), nullable=False)
    kullanici_adi = db.Column(db.String(80), unique=True, nullable=False)
    sifre_hash = db.Column(db.String(255), nullable=False)
    telefon = db.Column(db.String(20), unique=True, nullable=False) # GÜNCELLENDİ: nullable=False, unique=True (Eğer farklı kuryeler aynı tel no'yu kullanamazsa)
    email = db.Column(db.String(120), unique=True, nullable=True)
    aktif_mi = db.Column(db.Boolean, default=True, nullable=False)
    olusturulma_tarihi = db.Column(db.DateTime, default=datetime.now)
    guncellenme_tarihi = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    atanmis_kargolar = db.relationship('Kargolar', backref='atanan_kurye', lazy='dynamic', foreign_keys='Kargolar.kurye_id')
    bildirimler = db.relationship('Bildirimler', backref='kurye_bildirimleri', lazy='dynamic', foreign_keys='Bildirimler.kurye_id')

    def __repr__(self):
        return f'<Kurye {self.kullanici_adi} ({self.ad_soyad})>'

    def set_password(self, password):
        self.sifre_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.sifre_hash, password)

class AdminKullanicilar(db.Model):
    __tablename__ = 'admin_kullanicilar'
    id = db.Column(db.Integer, primary_key=True)
    kullanici_adi = db.Column(db.String(80), unique=True, nullable=False)
    sifre_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    olusturulma_tarihi = db.Column(db.DateTime, default=datetime.now)
    
    bildirimler = db.relationship('Bildirimler', backref='admin_bildirimleri', lazy='dynamic', foreign_keys='Bildirimler.admin_id')

    def __repr__(self):
        return f'<Admin {self.kullanici_adi}>'
    
    def set_password(self, password):
        self.sifre_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.sifre_hash, password)

class IsletmeOdemeleri(db.Model):
    __tablename__ = 'isletme_odemeleri'
    id = db.Column(db.Integer, primary_key=True)
    isletme_id = db.Column(db.Integer, db.ForeignKey('isletmeler.id'), nullable=False)
    odeme_tarihi = db.Column(db.Date, nullable=False) 
    odenen_tutar = db.Column(db.Numeric(10, 2), nullable=False)
    aciklama = db.Column(db.Text, nullable=True)
    islem_referansi = db.Column(db.String(100), nullable=True)
    olusturulma_tarihi = db.Column(db.DateTime, default=datetime.now)
    
    kargo_iliskileri = db.relationship('OdemeKargoIliskileri', backref='odeme', lazy='dynamic')

    def __repr__(self):
        return f'<Ödeme {self.id} - İşletme {self.isletme_id} - Tutar {self.odenen_tutar}>'

class Bildirimler(db.Model):
    __tablename__ = 'bildirimler'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin_kullanicilar.id'), nullable=True)
    isletme_id = db.Column(db.Integer, db.ForeignKey('isletmeler.id'), nullable=True)
    kurye_id = db.Column(db.Integer, db.ForeignKey('kuryeler.id'), nullable=True)

    mesaj = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=True) 
    okundu_mu = db.Column(db.Boolean, default=False, nullable=False)
    bildirim_tipi = db.Column(db.String(50), nullable=True) 
    olusturulma_tarihi = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        target_user = "Bilinmeyen"
        if self.admin_id:
            target_user = f"Admin ID: {self.admin_id}"
        elif self.isletme_id:
            target_user = f"İşletme ID: {self.isletme_id}"
        elif self.kurye_id:
            target_user = f"Kurye ID: {self.kurye_id}"
        return f'<Bildirim {self.id} - {target_user} - {self.mesaj[:20]}>'

class OdemeKargoIliskileri(db.Model):
    __tablename__ = 'odeme_kargo_iliskileri'
    id = db.Column(db.Integer, primary_key=True)
    odeme_id = db.Column(db.Integer, db.ForeignKey('isletme_odemeleri.id'), nullable=False)
    kargo_id = db.Column(db.Integer, db.ForeignKey('kargolar.id'), nullable=False)
    
    def __repr__(self):
        return f'<İlişki Ödeme {self.odeme_id} - Kargo {self.kargo_id}>'


# -----------------------------
# P0-3: Audit Log (kritik aksiyon kayıtları)
# -----------------------------
class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)

    # Kim yaptı?
    actor_type = db.Column(db.String(20), nullable=False, default="system")  # admin / isletme / kurye / system
    actor_id = db.Column(db.Integer, nullable=True)

    # Ne yaptı?
    action = db.Column(db.String(120), nullable=False)  # ör: "LOGIN_SUCCESS", "KARGO_OLUSTUR", "KARGO_DURUM_GUNCELLE"
    entity_type = db.Column(db.String(60), nullable=True)  # ör: "Kargolar", "Isletmeler"
    entity_id = db.Column(db.Integer, nullable=True)

    # Nereden yaptı?
    ip = db.Column(db.String(45), nullable=True)  # IPv4/IPv6
    user_agent = db.Column(db.String(255), nullable=True)

    # Ek detay
    details_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # Basit indexler (SQLite'da da çalışır)
    __table_args__ = (
        db.Index("ix_audit_log_created_at", "created_at"),
        db.Index("ix_audit_log_actor", "actor_type", "actor_id"),
        db.Index("ix_audit_log_entity", "entity_type", "entity_id"),
        db.Index("ix_audit_log_action", "action"),
    )

    def __repr__(self):
        return f"<AuditLog {self.id} {self.actor_type}:{self.actor_id} {self.action} {self.entity_type}:{self.entity_id}>"

    def details(self):
        """
        details_json alanını dict olarak döndürür.
        Bozuk JSON varsa güvenli şekilde None döner.
        """
        if not self.details_json:
            return None
        try:
            return json.loads(self.details_json)
        except Exception:
            return None


def create_audit_log(
    actor_type="system",
    actor_id=None,
    action="",
    entity_type=None,
    entity_id=None,
    ip=None,
    user_agent=None,
    details=None,
):
    """
    Audit log kaydı oluşturur.
    - details dict/list gibi bir şey ise JSON'a çevirir.
    - commit yapmaz: çağıran yer isterse commit eder (batch performansı).
    """
    if not action:
        # action boş olmasın; sessizce iptal etmek yerine açık hata üretelim
        raise ValueError("create_audit_log: action boş olamaz.")

    details_json = None
    if details is not None:
        try:
            details_json = json.dumps(details, ensure_ascii=False, default=str)
        except Exception:
            # details JSON'a çevrilemezse ham stringe düş
            details_json = json.dumps({"raw": str(details)}, ensure_ascii=False)

    log = AuditLog(
        actor_type=str(actor_type or "system")[:20],
        actor_id=actor_id,
        action=str(action)[:120],
        entity_type=(str(entity_type)[:60] if entity_type is not None else None),
        entity_id=entity_id,
        ip=(str(ip)[:45] if ip else None),
        user_agent=(str(user_agent)[:255] if user_agent else None),
        details_json=details_json,
    )

    db.session.add(log)
    return log

# app/models.py dosyasına bu sınıfı ekle (dosyanın sonuna ekleyebilirsin)

class LoginAttempt(db.Model):
    __tablename__ = 'login_attempts'
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), nullable=False)
    path = db.Column(db.String(100), nullable=False)
    count = db.Column(db.Integer, default=0)
    last_attempt_at = db.Column(db.DateTime, default=datetime.now)
    blocked_until = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index("ix_login_attempt_ip_path", "ip", "path"),
    )