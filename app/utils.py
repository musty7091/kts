# app/utils.py
from flask import url_for, current_app, render_template
from . import db, mail 
from .models import Bildirimler, Kargolar, Ayarlar, KargoDurumEnum # KargoDurumEnum import edildi
from decimal import Decimal
from datetime import datetime
import re
import json # kktc_konumlar için json.dumps kullanılacaksa (routes tarafında yapılıyor)
from flask_mail import Message
from threading import Thread

# KKTC Lokasyon Verisi (Önceki yanıtta tanımlandığı gibi)
kktc_konumlar = {
    "Lefkoşa": [
        "Akıncılar", "Alayköy", "Balıkesir", "Cihangir", "Değirmenlik", "Demirhan", "Dilekkaya", "Düzova",
        "Erdemli", "Gaziköy", "Gökhan", "Gönyeli", "Hamitköy", "Haspolat", "Kalavaç", "Kanlıköy", "Kırıkkale",
        "Kırklar", "Lefkoşa Merkez", "Meriç", "Minareliköy", "Türkeli", "Yeniceköy", "Yenikent", "Yılmazköy", "Yiğitler"
    ],
    "Gazimağusa": [
        "Akdoğan", "Akova", "Alaniçi", "Arıdamı", "Aslanköy", "Atlılar", "Beyarmudu", "Baykal", "Çamlıca",
        "Çanakkale", "Çayönü", "Çınarlı", "Dörtyol", "Düzce", "Ergenekon", "Gazimağusa Merkez", "Geçitkale",
        "Gönendere", "Görneç", "Güvercinlik", "İncirli", "İnönü", "Korkuteli", "Köprülü", "Kurudere",
        "Mallıdağ", "Mormenekşe", "Muratağa", "Mutluyaka", "Nergisli", "Paşaköy", "Pınarlı", "Pile",
        "Pirhan", "Sandallar", "Serdarlı", "Sütlüce", "Tatlısu", "Tirmen", "Turunçlu", "Tuzla",
        "Türkmenköy", "Ulukışla", "Vadili", "Yamaçköy", "Yeniboğaziçi", "Yıldırım"
    ],
    "Girne": [
        "Alsancak", "Aşağı Girne", "Aşağı Taşkent", "Bellapais", "Boğaz", "Çatalköy", "Doğanköy", "Esentepe",
        "Girne Merkez", "Karakum", "Karmi", "Karaoğlanoğlu", "Lapta", "Ozanköy", "Zeytinlik"
    ],
    "Güzelyurt": [
        "Aydınköy", "Bostancı", "Güzelyurt Merkez", "Gaziveren", "Mevlevi", "Serhatköy", "Zümrütköy", "Yeşilırmak"
    ],
    "İskele": [
        "Boğaziçi", "Ergazi", "İskele Merkez", "Kaleburnu", "Sipahi", "Yenierenköy", "Dipkarpaz", "Mehmetçik", "Bafra", "Ziyamet"
    ],
    "Lefke": [
        "Bağlıköy", "Doğancı", "Gemikonağı", "Lefke Merkez", "Yeşilyurt", "Yedidalga", "Bademliköy"
        # "Gaziveren" Güzelyurt listesinde olduğu için buradan çıkarıldı, çift girişi önlemek adına.
        # Eğer hem Güzelyurt'a hem Lefke'ye bağlı farklı Gaziveren bölgeleri varsa, isimleri ayırt edici olmalı.
    ]
}

def normalize_to_e164_tr(phone_number):
    """
    Verilen telefon numarasını Türkiye için E.164 formatına (+90XXXXXXXXXX) çevirmeye çalışır.
    KKTC numaraları için de +90 ön eki varsayılır. Farklı bir ön ek gerekiyorsa (örn: +357)
    bu fonksiyonun güncellenmesi gerekir.
    """
    if not phone_number:
        return None
    # Numaradaki tüm sayısal olmayan karakterleri temizle
    digits = re.sub(r'\D', '', str(phone_number))
    
    country_code_tr = "90" # Türkiye ve genellikle KKTC için kullanılan kod

    # +90 ile başlıyorsa ve doğru uzunluktaysa (12 haneli: +90 ve 10 haneli numara)
    if digits.startswith(country_code_tr) and len(digits) == (len(country_code_tr) + 10):
        return "+" + digits
    # 0 ile başlıyorsa ve doğru uzunluktaysa (11 haneli: 0 ve 10 haneli numara)
    elif digits.startswith("0") and len(digits) == 11:
        return "+" + country_code_tr + digits[1:]
    # Başında 0 veya +90 yoksa ve 10 haneli ise (örn: 5xxxxxxxxx)
    elif len(digits) == 10:
        return "+" + country_code_tr + digits
    
    # Diğer durumlar için uyarı ver ve None dön (örn: çok kısa, çok uzun, bilinmeyen format)
    current_app.logger.warning(f"Telefon numarası ({phone_number}) E.164 formatına çevrilemedi. Sayısal hali: {digits}")
    return None

def create_notification(user_type, user_id, message, link_endpoint=None, link_params=None, bildirim_tipi=None):
    """
    Belirtilen kullanıcı için bir bildirim oluşturur.
    db.session.commit() bu fonksiyon içinde ÇAĞIRILMAZ, route fonksiyonunda çağrılmalıdır.
    """
    link = None
    if link_endpoint:
        try:
            # _external=True parametresi tam URL oluşturmak için eklenebilir, eğer bildirimler
            # e-posta gibi sistem dışı bir yere de gidecekse. Şimdilik iç linkler için False.
            link = url_for(link_endpoint, **(link_params or {}))
        except Exception as e:
            current_app.logger.error(f"Bildirim linki oluşturulamadı ({link_endpoint}): {e}", exc_info=True)

    notification = Bildirimler(
        mesaj=message,
        link=link,
        bildirim_tipi=bildirim_tipi,
        okundu_mu=False # Yeni bildirimler her zaman okunmamış başlar
    )

    if user_type == 'admin':
        notification.admin_id = user_id
    elif user_type == 'isletme':
        notification.isletme_id = user_id
    elif user_type == 'kurye':
        notification.kurye_id = user_id
    else:
        current_app.logger.error(f"Bilinmeyen kullanıcı tipi ({user_type}) için bildirim oluşturulamadı. Mesaj: {message}")
        return # Hatalı tipte bildirim eklenmemeli

    try:
        db.session.add(notification)
        # db.session.commit() BURADA YAPILMAMALI! Çağıran yerde yapılmalı.
    except Exception as e:
        db.session.rollback() # Hata durumunda rollback
        current_app.logger.error(f"Bildirim veritabanına eklenirken hata: {e}", exc_info=True)

def send_async_email(app, msg):
    """E-postayı asenkron olarak gönderir."""
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            # E-posta gönderim hatalarını logla ama programın akışını kesme
            app.logger.error(f"Asenkron e-posta gönderilirken hata oluştu: {e}", exc_info=True)

def send_email_notification(recipient_email, subject, template_name, **kwargs):
    """
    Alıcıya belirtilen şablonu kullanarak e-posta gönderir.
    E-posta gönderimi asenkron olarak yapılır.
    """
    if not recipient_email or not subject or not template_name:
        current_app.logger.error("E-posta gönderilemedi: Alıcı, konu veya şablon adı eksik.")
        return False

    try:
        # MAIL_DEFAULT_SENDER config.py'de ('İsim', 'adres@example.com') formatında olmalı
        sender_config = current_app.config.get('MAIL_DEFAULT_SENDER', 'BeeCargo <noreply@example.com>')
        
        msg = Message(subject,
                      sender=sender_config, 
                      recipients=[recipient_email])
        
        # Şablona gönderilecek context'i oluştur
        template_context = kwargs.copy()
        template_context['subject'] = subject # Şablonun da konuya erişebilmesi için
        
        msg.html = render_template(f'email/{template_name}.html', **template_context)
        
        # Asenkron gönderme için thread kullan
        # current_app._get_current_object() ile güncel uygulama örneğini al
        app_context = current_app._get_current_object() 
        thr = Thread(target=send_async_email, args=[app_context, msg])
        thr.start()
        
        current_app.logger.info(f"E-posta gönderim isteği başarıyla kuyruğa alındı. Kime: {recipient_email}, Konu: {subject}")
        return True
    except Exception as e:
        current_app.logger.error(f"E-posta ({recipient_email}) gönderimi sırasında genel hata: {e}", exc_info=True)
        return False

def calculate_business_earnings(isletme_id, start_date=None, end_date=None):
    """
    Belirli bir işletmenin belirtilen tarih aralığındaki teslim edilmiş kargolardan
    elde ettiği toplam hizmet bedelini hesaplar.
    """
    sabit_kargo_ayari = Ayarlar.query.filter_by(ayar_adi='sabit_kargo_hizmet_bedeli').first()
    standart_hizmet_bedeli = Decimal(sabit_kargo_ayari.ayar_degeri.replace(',', '.')) if sabit_kargo_ayari and sabit_kargo_ayari.ayar_degeri else Decimal('100.00')
    
    # Kargo sorgusunu başlat
    query = Kargolar.query.filter_by(
        isletme_id=isletme_id,
        kargo_durumu=KargoDurumEnum.TESLIM_EDILDI # KargoDurumEnum burada kullanılacak
    )
    
    # Tarih aralığı filtresi (eğer belirtilmişse)
    if start_date and end_date:
        # Tarihleri datetime objelerine çevirerek tam gün aralığını kapsa
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
        query = query.filter(Kargolar.teslim_tarihi >= start_datetime, Kargolar.teslim_tarihi <= end_datetime)
    
    teslim_edilmis_kargolar = query.all()
    
    toplam_kazanc = Decimal('0.00')
    for kargo_item in teslim_edilmis_kargolar:
        # Kazanç hesaplama mantığı (öncekiyle aynı)
        if kargo_item.odeme_yontemi_teslimde == "Kapıda Nakit" and \
           kargo_item.kargo_ucreti_isletme_borcu == Decimal('0.00') and \
           kargo_item.kargo_ucreti_alici_tahsil >= standart_hizmet_bedeli:
            toplam_kazanc += standart_hizmet_bedeli
        else:
            toplam_kazanc += kargo_item.kargo_ucreti_isletme_borcu
            
    return toplam_kazanc
