# app/routes_business.py
import re
import json
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, current_app
)
from .models import (
    Isletmeler, Kargolar, Ayarlar, IsletmeOdemeleri, 
    OdemeKargoIliskileri, AdminKullanicilar, KargoDurumEnum
)
from . import db
from .utils import (
    create_notification, send_email_notification, 
    normalize_to_e164_tr, kktc_konumlar
)
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

bp_business = Blueprint('bp_business', __name__, template_folder='templates', url_prefix='/business')

# --- Diğer route fonksiyonları burada yer alıyor (login, dashboard, add_shipment, edit_shipment vb.) ---
# Bu fonksiyonlar önceki yanıtlarda verildiği gibi kalacak.
# Sadece 'change_password' ve 'logout' fonksiyonları güncellenecek/kontrol edilecek.

@bp_business.route('/login', methods=['GET', 'POST'])
def login():
    if 'isletme_id' in session:
        return redirect(url_for('bp_business.dashboard'))
    if request.method == 'POST':
        kullanici_adi = request.form.get('kullanici_adi')
        sifre = request.form.get('sifre')
        isletme_obj = Isletmeler.query.filter_by(kullanici_adi=kullanici_adi).first()
        if isletme_obj and isletme_obj.aktif_mi and check_password_hash(isletme_obj.sifre_hash, sifre):
            session['isletme_id'] = isletme_obj.id
            session['isletme_kullanici_adi'] = isletme_obj.kullanici_adi
            session['isletme_adi'] = isletme_obj.isletme_adi
            flash('İşletme olarak başarıyla giriş yaptınız!', 'success')
            return redirect(url_for('bp_business.dashboard'))
        elif isletme_obj and not isletme_obj.aktif_mi:
            flash('İşletme hesabınız pasif durumdadır. Lütfen yönetici ile iletişime geçin.', 'error')
        else:
            flash('Kullanıcı adı veya şifre hatalı.', 'error')
        return redirect(url_for('bp_business.login'))
    return render_template('business_login.html')

@bp_business.route('/dashboard')
def dashboard():
    if 'isletme_id' not in session:
        flash('Bu sayfayı görüntülemek için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))
    
    isletme_id_session = session['isletme_id']
    isletme_verileri = {} 
    
    query = Kargolar.query.filter_by(isletme_id=isletme_id_session)

    takip_no_search = request.args.get('takip_no', '').strip()
    alici_adi_search = request.args.get('alici_adi', '').strip()
    alici_telefon_search = request.args.get('alici_telefon', '').strip() 
    kargo_durumu_filter_str = request.args.get('kargo_durumu', '') 
    baslangic_tarihi_str = request.args.get('baslangic_tarihi', '')
    bitis_tarihi_str = request.args.get('bitis_tarihi', '')

    if takip_no_search:
        query = query.filter(Kargolar.takip_numarasi.ilike(f"%{takip_no_search}%"))
    if alici_adi_search:
        query = query.filter(Kargolar.alici_adi_soyadi.ilike(f"%{alici_adi_search}%"))
    
    if alici_telefon_search:
        normalized_search_phone_for_filter = normalize_to_e164_tr(alici_telefon_search)
        if normalized_search_phone_for_filter:
            query = query.filter(Kargolar.alici_telefon == normalized_search_phone_for_filter)

    if kargo_durumu_filter_str:
        try:
            kargo_durumu_enum_val = KargoDurumEnum(kargo_durumu_filter_str)
            query = query.filter(Kargolar.kargo_durumu == kargo_durumu_enum_val)
        except ValueError:
            flash(f"Geçersiz kargo durumu filtresi: {kargo_durumu_filter_str}", "warning")

    if baslangic_tarihi_str:
        try:
            baslangic_tarihi = datetime.strptime(baslangic_tarihi_str, '%Y-%m-%d').date()
            query = query.filter(Kargolar.olusturulma_tarihi >= datetime.combine(baslangic_tarihi, datetime.min.time()))
        except ValueError:
            flash('Geçersiz başlangıç tarihi formatı.', 'warning')
            
    if bitis_tarihi_str:
        try:
            bitis_tarihi = datetime.strptime(bitis_tarihi_str, '%Y-%m-%d').date()
            query = query.filter(Kargolar.olusturulma_tarihi <= datetime.combine(bitis_tarihi, datetime.max.time()))
        except ValueError:
            flash('Geçersiz bitiş tarihi formatı.', 'warning')

    try:
        isletmenin_kargolari = query.order_by(Kargolar.olusturulma_tarihi.desc()).all()
        isletme_verileri['kargolar'] = isletmenin_kargolari
    except Exception as e:
        flash(f"Kargolar listelenirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"İşletme dashboard kargo listeleme hatası: {e}", exc_info=True)
        isletme_verileri['kargolar'] = []

    try:
        net_alacak_kapida_nakit = db.session.query(
            func.sum(Kargolar.isletmeye_aktarilacak_tutar - Kargolar.kargo_ucreti_isletme_borcu)
        ).filter(
            Kargolar.isletme_id == isletme_id_session,
            Kargolar.isletmeye_aktarildi_mi == False, 
            Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI,
            Kargolar.odeme_yontemi_teslimde == "Kapıda Nakit" 
        ).scalar() or Decimal('0.00')
        
        borc_diger_yontemler_hizmet_bedeli = db.session.query(
            func.sum(Kargolar.kargo_ucreti_isletme_borcu)
        ).filter(
            Kargolar.isletme_id == isletme_id_session,
            Kargolar.isletmeye_aktarildi_mi == False,
            Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI,
            Kargolar.odeme_yontemi_teslimde.in_(["Online / Havale", "Kapıda Kredi Kartı"])
        ).scalar() or Decimal('0.00')

        isletme_verileri['toplam_alacak'] = net_alacak_kapida_nakit - borc_diger_yontemler_hizmet_bedeli
        
        son_odemeler = IsletmeOdemeleri.query.filter_by(isletme_id=isletme_id_session).order_by(IsletmeOdemeleri.odeme_tarihi.desc()).limit(5).all()
        isletme_verileri['son_odemeler'] = son_odemeler

    except Exception as e:
        flash(f"Panel finansal verileri getirilirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"İşletme dashboard finansal veri hatası: {e}", exc_info=True)
        if 'toplam_alacak' not in isletme_verileri: isletme_verileri['toplam_alacak'] = Decimal('0.00')
        if 'son_odemeler' not in isletme_verileri: isletme_verileri['son_odemeler'] = []
    
    return render_template('business_dashboard.html', KargoDurumEnum=KargoDurumEnum, **isletme_verileri)

@bp_business.route('/add_shipment', methods=['GET', 'POST'])
def add_shipment():
    if 'isletme_id' not in session:
        flash('Bu işlemi yapmak için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))
    
    isletme_baslangic_durumlari = [
        KargoDurumEnum.HAZIRLANIYOR,
        KargoDurumEnum.PAKETLENDI,
        KargoDurumEnum.KURYE_TESLIM_HAZIR,
        KargoDurumEnum.MUSTERIDEN_ALINMAYI_BEKLIYOR 
    ]
    
    kktc_konumlar_json = json.dumps(kktc_konumlar) 
    template_context = {
        "form_data": {}, 
        "isletme_baslangic_durumlari": isletme_baslangic_durumlari,
        "KargoDurumEnum": KargoDurumEnum,
        "kktc_ilceler": kktc_konumlar.keys(), 
        "kktc_konumlar_json": kktc_konumlar_json 
    }

    if request.method == 'POST':
        template_context["form_data"] = request.form 
        try:
            alici_adi_soyadi = request.form.get('alici_adi_soyadi')
            alici_telefon_form = request.form.get('alici_telefon', '').strip()
            alici_email_form = request.form.get('alici_email', '').strip() 
            alici_adres_detay = request.form.get('alici_adres') 
            alici_ilce_secilen = request.form.get('alici_sehir') 
            alici_koy_secilen = request.form.get('alici_ilce')   
            ozel_not = request.form.get('ozel_not')
            kargo_durumu_form_str = request.form.get('kargo_durumu', KargoDurumEnum.HAZIRLANIYOR.value) 
            odeme_yontemi = request.form.get('odeme_yontemi_teslimde')

            if not alici_telefon_form:
                flash('Alıcı Telefon numarası zorunludur.', 'error')
                return render_template('business_add_shipment.html', **template_context)

            normalized_alici_telefon = normalize_to_e164_tr(alici_telefon_form)
            if not normalized_alici_telefon:
                flash('Geçersiz alıcı telefon numarası formatı. Lütfen E.164 formatında girin (örn: +905xxxxxxxxx).', 'error')
                return render_template('business_add_shipment.html', **template_context)
            
            if alici_email_form and not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", alici_email_form):
                flash('Geçersiz alıcı e-posta formatı.', 'error')
                return render_template('business_add_shipment.html', **template_context)

            try:
                kargo_durumu_form_enum = KargoDurumEnum(kargo_durumu_form_str)
                if kargo_durumu_form_enum not in isletme_baslangic_durumlari:
                    flash('Geçersiz başlangıç kargo durumu seçildi. Lütfen listeden seçin.', 'error')
                    return render_template('business_add_shipment.html', **template_context)
            except ValueError:
                flash('Geçersiz başlangıç kargo durumu değeri.', 'error')
                return render_template('business_add_shipment.html', **template_context)

            try:
                urun_bedeli_alici_tahsil_str = request.form.get('urun_bedeli_alici_tahsil', '0').replace(',', '.')
                urun_bedeli_decimal = Decimal(urun_bedeli_alici_tahsil_str if urun_bedeli_alici_tahsil_str else '0')
                kargo_ucreti_alici_tahsil_str = request.form.get('kargo_ucreti_alici_tahsil', '0').replace(',', '.')
                kargo_ucreti_alici_tahsil_decimal = Decimal(kargo_ucreti_alici_tahsil_str if kargo_ucreti_alici_tahsil_str else '0')

                if urun_bedeli_decimal < 0 or kargo_ucreti_alici_tahsil_decimal < 0:
                    flash('Ürün bedeli ve alıcıdan tahsil edilecek kargo ücreti negatif olamaz.', 'error')
                    return render_template('business_add_shipment.html', **template_context)
            except InvalidOperation:
                flash('Lütfen geçerli bir ürün bedeli veya kargo ücreti girin (örn: 123.45).', 'error')
                return render_template('business_add_shipment.html', **template_context)

            if not all([alici_adi_soyadi, alici_adres_detay, alici_ilce_secilen, odeme_yontemi]): 
                flash('Lütfen tüm zorunlu (*) alanları (Alıcı Adı, Açık Adres, İlçe, Ödeme Yöntemi) doldurun.', 'error')
                return render_template('business_add_shipment.html', **template_context)
            
            isletme_id_session = session.get('isletme_id')
            current_isletme = Isletmeler.query.get(isletme_id_session)
            if not current_isletme:
                flash('İşletme bilgileri bulunamadı. Lütfen tekrar giriş yapın.', 'error')
                session.pop('isletme_id', None) 
                return redirect(url_for('bp_business.login'))

            sabit_kargo_ayari = Ayarlar.query.filter_by(ayar_adi='sabit_kargo_hizmet_bedeli').first()
            standart_hizmet_bedeli = Decimal(sabit_kargo_ayari.ayar_degeri.replace(',', '.')) if sabit_kargo_ayari and sabit_kargo_ayari.ayar_degeri else Decimal('100.00')
            
            current_isletme.son_kargo_no = (current_isletme.son_kargo_no or 0) + 1
            takip_numarasi_yeni = f"{current_isletme.isletme_kodu}-{str(current_isletme.son_kargo_no).zfill(6)}"
            
            isletmeye_aktarilacak_hesaplanan = Decimal('0.00')
            mevcut_kargo_isletme_borcu = standart_hizmet_bedeli
            odeme_durumu_alici_yeni = "Alıcıdan Ödeme Bekleniyor"

            if odeme_yontemi == "Online / Havale":
                isletmeye_aktarilacak_hesaplanan = Decimal('0.00') 
                odeme_durumu_alici_yeni = "Online/Havale Ödendi"
            elif odeme_yontemi == "Kapıda Kredi Kartı": 
                isletmeye_aktarilacak_hesaplanan = Decimal('0.00') 
                odeme_durumu_alici_yeni = "Alıcıdan Tahsil Edildi (İşletme KK)" 
            elif odeme_yontemi == "Kapıda Nakit":
                isletmeye_aktarilacak_hesaplanan = urun_bedeli_decimal 
                if kargo_ucreti_alici_tahsil_decimal >= standart_hizmet_bedeli:
                    mevcut_kargo_isletme_borcu = Decimal('0.00') 
                else: 
                    mevcut_kargo_isletme_borcu = standart_hizmet_bedeli - kargo_ucreti_alici_tahsil_decimal
                    if mevcut_kargo_isletme_borcu < 0: mevcut_kargo_isletme_borcu = Decimal('0.00')
                odeme_durumu_alici_yeni = "Alıcıdan Ödeme Bekleniyor"

            yeni_kargo = Kargolar(
                isletme_id=isletme_id_session, 
                takip_numarasi=takip_numarasi_yeni,
                alici_adi_soyadi=alici_adi_soyadi, 
                alici_telefon=normalized_alici_telefon,
                alici_email=alici_email_form if alici_email_form else None,
                alici_adres=alici_adres_detay, 
                alici_sehir=alici_ilce_secilen, 
                alici_ilce=alici_koy_secilen if alici_koy_secilen else None, 
                urun_bedeli_alici_tahsil=urun_bedeli_decimal,
                kargo_ucreti_isletme_borcu=mevcut_kargo_isletme_borcu,
                kargo_ucreti_alici_tahsil=kargo_ucreti_alici_tahsil_decimal,
                toplam_tahsil_edilecek_alici=(urun_bedeli_decimal + kargo_ucreti_alici_tahsil_decimal),
                isletmeye_aktarilacak_tutar=isletmeye_aktarilacak_hesaplanan, 
                odeme_yontemi_teslimde=odeme_yontemi,
                odeme_durumu_alici=odeme_durumu_alici_yeni,
                kargo_durumu=kargo_durumu_form_enum, 
                ozel_not=ozel_not,
                isletmeye_aktarildi_mi=False 
            )
            
            db.session.add(yeni_kargo)
            db.session.add(current_isletme) 
            db.session.commit()

            try:
                admin_users = AdminKullanicilar.query.all() 
                if admin_users:
                    for admin_user in admin_users:
                        create_notification(
                            user_type='admin', user_id=admin_user.id,
                            message=f"'{current_isletme.isletme_adi}' yeni kargo oluşturdu: {yeni_kargo.takip_numarasi}",
                            link_endpoint='bp_admin.shipment_details', link_params={'kargo_id': yeni_kargo.id},
                            bildirim_tipi='yeni_kargo_kaydi'
                        )
                    db.session.commit() 
            except Exception as e_notify_admin:
                db.session.rollback()
                current_app.logger.error(f"Yeni kargo ({yeni_kargo.takip_numarasi}) için admin bildirimi oluşturulurken hata: {e_notify_admin}", exc_info=True)

            if yeni_kargo.alici_email: 
                email_subject_str = f"{current_app.config.get('SITE_NAME', 'BeeCargo')} - Kargonuz Hazırlanıyor ({yeni_kargo.takip_numarasi})"
                email_template_params = {
                    'alici_adi_soyadi': yeni_kargo.alici_adi_soyadi,
                    'isletme_adi': current_isletme.isletme_adi,
                    'takip_numarasi': yeni_kargo.takip_numarasi,
                    'site_name': current_app.config.get('SITE_NAME', 'BeeCargo'),
                    'takip_url': url_for('bp_common.track_shipment_public_input', takip_no=yeni_kargo.takip_numarasi, _external=True),
                    'site_logo_url': url_for('static', filename='images/bee.jpg', _external=True), # LOGO GÜNCELLENDİ
                    'isletme_iletisim': current_isletme.isletme_telefon or current_isletme.isletme_email,
                    'now': datetime.now() 
                }
                email_sent = send_email_notification(
                    recipient_email=yeni_kargo.alici_email,
                    subject=email_subject_str,
                    template_name='kargo_hazirlandi_bildirimi', 
                    **email_template_params
                )
                if email_sent:
                    flash(f"'{yeni_kargo.takip_numarasi}' takip numaralı kargo eklendi ve alıcıya bilgilendirme e-postası gönderildi.", 'success')
                else:
                    flash(f"'{yeni_kargo.takip_numarasi}' takip numaralı kargo eklendi, ancak alıcıya e-posta gönderilirken bir sorun oluştu.", 'warning')
            else: 
                 flash(f"'{yeni_kargo.takip_numarasi}' takip numaralı kargo eklendi. Alıcı e-posta adresi girilmediği için bildirim gönderilmedi.", 'info')
            
            return redirect(url_for('bp_business.dashboard'))

        except Exception as e_outer:
            db.session.rollback()
            flash(f"Kargo eklenirken genel bir hata oluştu: {str(e_outer)}", 'error')
            current_app.logger.error(f"Kargo ekleme dış blok hatası: {e_outer}", exc_info=True)
            return render_template('business_add_shipment.html', **template_context)
        
    return render_template('business_add_shipment.html', **template_context)

@bp_business.route('/edit_shipment/<int:kargo_id>', methods=['GET', 'POST'])
def edit_shipment(kargo_id):
    if 'isletme_id' not in session:
        flash('Bu işlemi yapmak için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))

    kargo = Kargolar.query.filter_by(id=kargo_id, isletme_id=session['isletme_id']).first_or_404()
    kktc_konumlar_json = json.dumps(kktc_konumlar)

    kurye_admin_islem_durumlari = [
        KargoDurumEnum.KARGO_ALINDI_MERKEZDE, KargoDurumEnum.DAGITIMDA, 
        KargoDurumEnum.TESLIM_EDILDI, KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI, 
        KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI, KargoDurumEnum.IADE_SURECINDE, 
        KargoDurumEnum.IADE_EDILDI_ISLETMEYE, KargoDurumEnum.IPTAL_EDILDI_ADMIN
    ]

    if kargo.isletmeye_aktarildi_mi:
        flash(f"'{kargo.takip_numarasi}' takip numaralı kargonun ödemesi yapıldığı için bilgileri değiştirilemez.", 'warning')
        return redirect(url_for('bp_business.shipment_details', kargo_id=kargo.id))
    
    if kargo.kargo_durumu in kurye_admin_islem_durumlari:
        flash(f"Bu kargo ({kargo.kargo_durumu.value}) kurye/admin tarafından işleme alındığı için bilgileri işletme tarafından değiştirilemez.", 'warning')
        return redirect(url_for('bp_business.shipment_details', kargo_id=kargo.id))

    finansal_duzenlenebilir = kargo.kargo_durumu == KargoDurumEnum.HAZIRLANIYOR
    adres_ozelnot_duzenlenebilir = kargo.kargo_durumu in [
        KargoDurumEnum.HAZIRLANIYOR, 
        KargoDurumEnum.PAKETLENDI, 
        KargoDurumEnum.KURYE_TESLIM_HAZIR,
        KargoDurumEnum.MUSTERIDEN_ALINMAYI_BEKLIYOR
    ]
    
    template_context = {
        "kargo": kargo,
        "finansal_duzenlenebilir": finansal_duzenlenebilir,
        "adres_ozelnot_duzenlenebilir": adres_ozelnot_duzenlenebilir,
        "kktc_ilceler": kktc_konumlar.keys(),
        "kktc_konumlar_json": kktc_konumlar_json,
        "KargoDurumEnum": KargoDurumEnum,
        "form_data": {} 
    }

    if request.method == 'POST':
        template_context["form_data"] = request.form
        original_odeme_yontemi = kargo.odeme_yontemi_teslimde 

        if adres_ozelnot_duzenlenebilir:
            kargo.alici_adi_soyadi = request.form.get('alici_adi_soyadi', kargo.alici_adi_soyadi).strip()
            alici_telefon_form_edit = request.form.get('alici_telefon', kargo.alici_telefon).strip()
            
            if not alici_telefon_form_edit:
                flash('Alıcı Telefon numarası zorunludur.', 'error')
                return render_template('business_edit_shipment.html', **template_context)

            normalized_alici_telefon_edit = normalize_to_e164_tr(alici_telefon_form_edit)
            if not normalized_alici_telefon_edit:
                flash('Geçersiz alıcı telefon numarası formatı. Lütfen E.164 formatında girin (örn: +905xxxxxxxxx).', 'error')
                return render_template('business_edit_shipment.html', **template_context)
            kargo.alici_telefon = normalized_alici_telefon_edit
            
            alici_email_form_edit = request.form.get('alici_email', (kargo.alici_email or '')).strip()
            if alici_email_form_edit and not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", alici_email_form_edit):
                flash('Geçersiz alıcı e-posta formatı.', 'error')
                return render_template('business_edit_shipment.html', **template_context)
            kargo.alici_email = alici_email_form_edit if alici_email_form_edit else None
            
            kargo.alici_adres = request.form.get('alici_adres', kargo.alici_adres).strip() 
            kargo.alici_sehir = request.form.get('alici_sehir', kargo.alici_sehir).strip() 
            kargo.alici_ilce = request.form.get('alici_ilce', kargo.alici_ilce or '').strip() 
            kargo.ozel_not = request.form.get('ozel_not', kargo.ozel_not or '').strip()

            if not all([kargo.alici_adi_soyadi, kargo.alici_adres, kargo.alici_sehir]): 
                flash('Alıcı Adı, Açık Adres ve İlçe alanları zorunludur.', 'error')
                return render_template('business_edit_shipment.html', **template_context)
        
        if finansal_duzenlenebilir:
            try:
                urun_bedeli_str = request.form.get('urun_bedeli_alici_tahsil', str(kargo.urun_bedeli_alici_tahsil)).replace(',', '.')
                kargo.urun_bedeli_alici_tahsil = Decimal(urun_bedeli_str if urun_bedeli_str else '0')
                
                kargo_ucreti_alici_str = request.form.get('kargo_ucreti_alici_tahsil', str(kargo.kargo_ucreti_alici_tahsil)).replace(',', '.')
                kargo.kargo_ucreti_alici_tahsil = Decimal(kargo_ucreti_alici_str if kargo_ucreti_alici_str else '0')

                if kargo.urun_bedeli_alici_tahsil < 0 or kargo.kargo_ucreti_alici_tahsil < 0:
                    flash('Ürün bedeli ve alıcıdan tahsil edilecek kargo ücreti negatif olamaz.', 'error')
                    return render_template('business_edit_shipment.html', **template_context)

                kargo.toplam_tahsil_edilecek_alici = kargo.urun_bedeli_alici_tahsil + kargo.kargo_ucreti_alici_tahsil
                
                sabit_kargo_ayari = Ayarlar.query.filter_by(ayar_adi='sabit_kargo_hizmet_bedeli').first()
                standart_hizmet_bedeli = Decimal(sabit_kargo_ayari.ayar_degeri.replace(',', '.')) if sabit_kargo_ayari and sabit_kargo_ayari.ayar_degeri else Decimal('100.00')
                
                mevcut_kargo_isletme_borcu_guncel = standart_hizmet_bedeli
                isletmeye_aktarilacak_guncel = Decimal('0.00')

                if original_odeme_yontemi == "Online / Havale" or original_odeme_yontemi == "Kapıda Kredi Kartı":
                    isletmeye_aktarilacak_guncel = Decimal('0.00') 
                elif original_odeme_yontemi == "Kapıda Nakit":
                    isletmeye_aktarilacak_guncel = kargo.urun_bedeli_alici_tahsil 
                    if kargo.kargo_ucreti_alici_tahsil >= standart_hizmet_bedeli: 
                        mevcut_kargo_isletme_borcu_guncel = Decimal('0.00')
                    else:
                        mevcut_kargo_isletme_borcu_guncel = standart_hizmet_bedeli - kargo.kargo_ucreti_alici_tahsil
                        if mevcut_kargo_isletme_borcu_guncel < 0: mevcut_kargo_isletme_borcu_guncel = Decimal('0.00')
                
                kargo.isletmeye_aktarilacak_tutar = isletmeye_aktarilacak_guncel
                kargo.kargo_ucreti_isletme_borcu = mevcut_kargo_isletme_borcu_guncel
            except InvalidOperation:
                flash('Lütfen geçerli bir ürün bedeli veya kargo ücreti girin (örn: 123.45).', 'error')
                return render_template('business_edit_shipment.html', **template_context)
        
        try:
            kargo.guncellenme_tarihi = datetime.now()
            db.session.commit() 
            flash(f"'{kargo.takip_numarasi}' takip numaralı kargo bilgileri başarıyla güncellendi.", 'success')
            return redirect(url_for('bp_business.shipment_details', kargo_id=kargo.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Kargo güncellenirken bir hata oluştu: {str(e)}", 'error')
            current_app.logger.error(f"Kargo ({kargo.id}) güncelleme hatası: {e}", exc_info=True)
            return render_template('business_edit_shipment.html', **template_context)

    if not request.form: 
        template_context["form_data"] = {
            'alici_adi_soyadi': kargo.alici_adi_soyadi, 
            'alici_telefon': kargo.alici_telefon, 
            'alici_email': kargo.alici_email or '',
            'alici_adres': kargo.alici_adres, 
            'alici_sehir': kargo.alici_sehir, 
            'alici_ilce': kargo.alici_ilce or '', 
            'ozel_not': kargo.ozel_not or '',
            'urun_bedeli_alici_tahsil': str(kargo.urun_bedeli_alici_tahsil),
            'kargo_ucreti_alici_tahsil': str(kargo.kargo_ucreti_alici_tahsil)
        }
    return render_template('business_edit_shipment.html', **template_context)

@bp_business.route('/change-password', methods=['GET', 'POST'])
def change_password():
    if 'isletme_id' not in session:
        flash('Bu işlemi yapmak için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))

    isletme = Isletmeler.query.get_or_404(session['isletme_id'])
    form_data = {} # Hata durumunda formu dolu tutmak için

    if request.method == 'POST':
        form_data = request.form.to_dict() # Form verilerini al
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_new_password = request.form.get('confirm_new_password')

        if not all([current_password, new_password, confirm_new_password]):
            flash('Lütfen tüm şifre alanlarını doldurun.', 'error')
        elif not check_password_hash(isletme.sifre_hash, current_password):
            flash('Mevcut şifreniz yanlış.', 'error')
        elif new_password != confirm_new_password:
            flash('Yeni şifreler eşleşmiyor.', 'error')
            # Sadece current_password'ı koru, yeni şifre alanlarını temizle
            form_data['new_password'] = '' 
            form_data['confirm_new_password'] = ''
        else:
            errors = []
            if len(new_password) < 8: errors.append("Yeni şifre en az 8 karakter olmalıdır.")
            if not re.search(r"[A-Z]", new_password): errors.append("Yeni şifre en az bir büyük harf içermelidir.")
            if not re.search(r"[a-z]", new_password): errors.append("Yeni şifre en az bir küçük harf içermelidir.")
            if not re.search(r"[0-9]", new_password): errors.append("Yeni şifre en az bir rakam içermelidir.")
            if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?~`]", new_password): errors.append("Yeni şifre en az bir özel karakter içermelidir.")

            if errors:
                for error_msg in errors: flash(error_msg, 'error')
                # Hatalı durumda current_password'ı koru, yeni şifre alanlarını temizle
                form_data['new_password'] = '' 
                form_data['confirm_new_password'] = ''
            else:
                try:
                    isletme.sifre_hash = generate_password_hash(new_password)
                    db.session.commit()
                    # Şifre başarıyla değiştirildi, oturumu sonlandır ve giriş sayfasına yönlendir
                    session.pop('isletme_id', None)
                    session.pop('isletme_kullanici_adi', None)
                    session.pop('isletme_adi', None)
                    flash('Şifreniz başarıyla güncellendi! Güvenlik nedeniyle tekrar giriş yapmanız gerekmektedir.', 'success')
                    return redirect(url_for('bp_business.login')) 
                except Exception as e:
                    db.session.rollback()
                    flash(f'Şifre güncellenirken bir hata oluştu: {str(e)}', 'error')
                    current_app.logger.error(f"İşletme ({isletme.id}) şifre güncelleme hatası: {e}", exc_info=True)
                    # Hata durumunda current_password'ı koru
                    # form_data zaten request.form.to_dict() ile alınmıştı, o değerler kalır.
        
        # Şifre formuyla ilgili bir işlem yapıldıysa (başarılı veya hatalı), sayfayı tekrar render et
        return render_template('business_change_password.html', isletme=isletme, form_data=form_data)

    # GET request için
    return render_template('business_change_password.html', isletme=isletme, form_data=form_data)

@bp_business.route('/logout')
def logout():
    session.pop('isletme_id', None)
    session.pop('isletme_kullanici_adi', None)
    session.pop('isletme_adi', None)
    flash('Başarıyla çıkış yaptınız.', 'success')
    return redirect(url_for('bp_common.index'))

# Diğer route fonksiyonları (update_status, payments, payment_details, shipment_details)
# önceki yanıtlarda verildiği gibi kalacak.
@bp_business.route('/update_status/<int:kargo_id>', methods=['GET', 'POST'])
def update_shipment_status(kargo_id):
    if 'isletme_id' not in session:
        flash('Bu işlemi yapmak için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))
    kargo_obj = Kargolar.query.filter_by(id=kargo_id, isletme_id=session['isletme_id']).first_or_404()
    
    if kargo_obj.isletmeye_aktarildi_mi:
        flash(f"'{kargo_obj.takip_numarasi}' takip numaralı kargonun ödemesi yapıldığı için durumu değiştirilemez.", 'warning')
        return redirect(url_for('bp_business.shipment_details', kargo_id=kargo_id))
    
    kurye_admin_islem_durumlari = [
        KargoDurumEnum.KARGO_ALINDI_MERKEZDE, KargoDurumEnum.DAGITIMDA, 
        KargoDurumEnum.TESLIM_EDILDI, KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI, 
        KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI, KargoDurumEnum.IADE_SURECINDE, 
        KargoDurumEnum.IADE_EDILDI_ISLETMEYE, KargoDurumEnum.IPTAL_EDILDI_ADMIN
    ]

    can_update_by_business = kargo_obj.kargo_durumu not in kurye_admin_islem_durumlari and not kargo_obj.isletmeye_aktarildi_mi
    
    gecerli_sonraki_durumlar_isletme = []
    if kargo_obj.kargo_durumu == KargoDurumEnum.HAZIRLANIYOR:
        gecerli_sonraki_durumlar_isletme = [KargoDurumEnum.PAKETLENDI, KargoDurumEnum.KURYE_TESLIM_HAZIR, KargoDurumEnum.IPTAL_EDILDI_ISLETME]
    elif kargo_obj.kargo_durumu == KargoDurumEnum.PAKETLENDI:
        gecerli_sonraki_durumlar_isletme = [KargoDurumEnum.HAZIRLANIYOR, KargoDurumEnum.KURYE_TESLIM_HAZIR, KargoDurumEnum.IPTAL_EDILDI_ISLETME]
    elif kargo_obj.kargo_durumu == KargoDurumEnum.KURYE_TESLIM_HAZIR:
        gecerli_sonraki_durumlar_isletme = [KargoDurumEnum.PAKETLENDI, KargoDurumEnum.IPTAL_EDILDI_ISLETME]
    elif kargo_obj.kargo_durumu == KargoDurumEnum.MUSTERIDEN_ALINMAYI_BEKLIYOR:
        gecerli_sonraki_durumlar_isletme = [KargoDurumEnum.IPTAL_EDILDI_ISLETME]

    form_data_on_error = {}
    if request.method == 'POST':
        form_data_on_error = request.form
        yeni_durum_str = request.form.get('yeni_kargo_durumu')
        
        if not can_update_by_business:
            flash(f"Bu kargonun ({kargo_obj.kargo_durumu.value}) durumu işletme tarafından şu anda değiştirilemez.", 'error')
        elif yeni_durum_str:
            try:
                yeni_durum_enum = KargoDurumEnum(yeni_durum_str)
                if yeni_durum_enum not in gecerli_sonraki_durumlar_isletme:
                     flash(f"'{yeni_durum_enum.value}' durumu mevcut durum ({kargo_obj.kargo_durumu.value}) için geçerli bir sonraki adım değil.", 'warning')
                elif kargo_obj.kargo_durumu == yeni_durum_enum:
                    flash("Kargo zaten bu durumda.", "info")
                else:
                    eski_durum_value = kargo_obj.kargo_durumu.value
                    kargo_obj.kargo_durumu = yeni_durum_enum
                    kargo_obj.guncellenme_tarihi = datetime.now()
                    db.session.commit()
                    
                    admin_users = AdminKullanicilar.query.all()
                    if admin_users:
                        for admin_user in admin_users:
                            create_notification(
                                user_type='admin', user_id=admin_user.id,
                                message=f"'{kargo_obj.isletme.isletme_adi}' işletmesi, {kargo_obj.takip_numarasi} nolu kargonun durumunu '{eski_durum_value}' -> '{yeni_durum_enum.value}' olarak güncelledi.",
                                link_endpoint='bp_admin.shipment_details', link_params={'kargo_id': kargo_obj.id},
                                bildirim_tipi='kargo_durum_isletme_guncellemesi'
                            )
                        db.session.commit()
                                        
                    flash(f"'{kargo_obj.takip_numarasi}' takip numaralı kargonun durumu '{yeni_durum_enum.value}' olarak güncellendi.", 'success')
                    return redirect(url_for('bp_business.dashboard'))
            except ValueError:
                 flash("Geçersiz bir durum değeri seçtiniz.", 'error')
            except Exception as e:
                db.session.rollback()
                flash(f"Durum güncellenirken bir hata oluştu: {str(e)}", 'error')
                current_app.logger.error(f"İşletme kargo ({kargo_obj.id}) durum güncelleme hatası: {e}", exc_info=True)
        else:
            flash("Lütfen yeni bir kargo durumu seçin.", 'error')
        
        return render_template('business_update_shipment_status.html', kargo=kargo_obj, guncellenebilir_durumlar=gecerli_sonraki_durumlar_isletme, form_data=form_data_on_error, can_update_by_business=can_update_by_business, KargoDurumEnum=KargoDurumEnum)
    
    return render_template('business_update_shipment_status.html', kargo=kargo_obj, guncellenebilir_durumlar=gecerli_sonraki_durumlar_isletme, form_data=form_data_on_error, can_update_by_business=can_update_by_business, KargoDurumEnum=KargoDurumEnum)

@bp_business.route('/payments')
def payments():
    if 'isletme_id' not in session:
        flash('Bu sayfayı görüntülemek için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))
    isletme_id_session = session['isletme_id']
    try:
        isletmenin_odemeleri = IsletmeOdemeleri.query.filter_by(isletme_id=isletme_id_session).order_by(IsletmeOdemeleri.odeme_tarihi.desc()).all()
    except Exception as e:
        flash(f"Ödeme geçmişi getirilirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"İşletme ödeme geçmişi getirme hatası: {e}", exc_info=True)
        isletmenin_odemeleri = []
    return render_template('business_payments.html', odemeler=isletmenin_odemeleri)

@bp_business.route('/payment_details/<int:odeme_id>')
def payment_details(odeme_id):
    if 'isletme_id' not in session:
        flash('Bu sayfayı görüntülemek için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))
    isletme_id_session = session['isletme_id']
    odeme_obj = None
    iliskili_kargolar = []
    try:
        odeme_obj = IsletmeOdemeleri.query.filter_by(id=odeme_id, isletme_id=isletme_id_session).first_or_404()
        iliskili_kargolar = Kargolar.query.join(
            OdemeKargoIliskileri, Kargolar.id == OdemeKargoIliskileri.kargo_id
        ).filter(OdemeKargoIliskileri.odeme_id == odeme_id).all()
    except Exception as e:
        flash(f"Ödeme detayları getirilirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"İşletme ödeme detayı ({odeme_id}) getirme hatası: {e}", exc_info=True)
    return render_template('business_payment_details.html', odeme_detayi=odeme_obj, iliskili_kargolar=iliskili_kargolar)

@bp_business.route('/shipment_details/<int:kargo_id>')
def shipment_details(kargo_id):
    if 'isletme_id' not in session:
        flash('Bu sayfayı görüntülemek için işletme olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_business.login'))
    isletme_id_session = session['isletme_id']
    kargo = Kargolar.query.filter_by(id=kargo_id, isletme_id=isletme_id_session).first_or_404()
    return render_template('shipment_details.html', kargo=kargo, KargoDurumEnum=KargoDurumEnum)
