# app/routes_courier.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from .models import Kuryeler, Kargolar, KargoDurumEnum, AdminKullanicilar 
from . import db
from .utils import create_notification 
from werkzeug.security import check_password_hash
from datetime import datetime

bp_courier = Blueprint('bp_courier', __name__, template_folder='templates/courier', url_prefix='/courier')

@bp_courier.route('/login', methods=['GET', 'POST'])
def login():
    if 'kurye_id' in session:
        return redirect(url_for('bp_courier.dashboard'))
    if request.method == 'POST':
        kullanici_adi = request.form.get('kullanici_adi')
        sifre = request.form.get('sifre')
        kurye = Kuryeler.query.filter_by(kullanici_adi=kullanici_adi).first()
        
        if kurye and kurye.aktif_mi and kurye.check_password(sifre):
            session['kurye_id'] = kurye.id
            session['kurye_kullanici_adi'] = kurye.kullanici_adi
            session['kurye_ad_soyad'] = kurye.ad_soyad
            flash('Kurye olarak başarıyla giriş yaptınız!', 'success')
            return redirect(url_for('bp_courier.dashboard'))
        elif kurye and not kurye.aktif_mi:
            flash('Kurye hesabınız pasif durumdadır. Lütfen yönetici ile iletişime geçin.', 'error')
        else:
            flash('Kullanıcı adı veya şifre hatalı.', 'error')
        return redirect(url_for('bp_courier.login'))
        
    return render_template('courier_login.html')

@bp_courier.route('/dashboard')
def dashboard():
    if 'kurye_id' not in session:
        flash('Bu sayfayı görüntülemek için kurye olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_courier.login'))
    
    kurye_id = session['kurye_id']
    atanmis_aktif_kargolar = []
    tamamlanmis_kargolar = []
    
    try:
        # Kuryenin aktif olarak ilgilenmesi gereken kargo durumları
        # KargoDurum Akış Kurgusuna göre güncellendi
        kurye_aktif_gorev_durumlari = [
            KargoDurumEnum.HAZIRLANIYOR,               # Admin bu durumda atama yapabilir
            KargoDurumEnum.PAKETLENDI,                 
            KargoDurumEnum.KURYE_TESLIM_HAZIR,         
            KargoDurumEnum.MUSTERIDEN_ALINMAYI_BEKLIYOR, 
            KargoDurumEnum.KARGO_ALINDI_MERKEZDE,     
            KargoDurumEnum.DAGITIMDA,
            # Teslim edilemeyen durumlar da aktif görev sayılabilir, kuryenin işlem yapması gerekebilir.
            KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI,
            KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI
        ]
        
        atanmis_aktif_kargolar = Kargolar.query.filter(
            Kargolar.kurye_id == kurye_id,
            Kargolar.kargo_durumu.in_(kurye_aktif_gorev_durumlari) 
        ).order_by(Kargolar.id.desc()).all() 

        kurye_tamamlanmis_durumlar = [
            KargoDurumEnum.TESLIM_EDILDI,
            KargoDurumEnum.IADE_EDILDI_ISLETMEYE 
        ]
        
        tamamlanmis_kargolar = Kargolar.query.filter(
            Kargolar.kurye_id == kurye_id,
            Kargolar.kargo_durumu.in_(kurye_tamamlanmis_durumlar)
        ).order_by(Kargolar.guncellenme_tarihi.desc()).limit(20).all() 
        
    except Exception as e:
        flash(f"Atanmış kargolar listelenirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"Kurye ({kurye_id}) dashboard kargo listeleme hatası: {e}", exc_info=True)
        
    return render_template('courier_dashboard.html', 
                           aktif_kargolar=atanmis_aktif_kargolar, 
                           tamamlanmis_kargolar=tamamlanmis_kargolar,
                           KargoDurumEnum=KargoDurumEnum)

@bp_courier.route('/logout')
def logout():
    session.pop('kurye_id', None)
    session.pop('kurye_kullanici_adi', None)
    session.pop('kurye_ad_soyad', None)
    flash('Başarıyla çıkış yaptınız.', 'success')
    return redirect(url_for('bp_common.index'))

@bp_courier.route('/shipment_action/<int:kargo_id>', methods=['GET', 'POST'])
def shipment_action_by_courier(kargo_id):
    if 'kurye_id' not in session:
        flash('Bu işlemi yapmak için kurye olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_courier.login'))

    kargo = Kargolar.query.filter_by(id=kargo_id, kurye_id=session['kurye_id']).first_or_404()

    # Kargonun mevcut durumuna göre kuryenin seçebileceği bir sonraki mantıksal durumlar
    gecerli_sonraki_durumlar = []
    mevcut_durum = kargo.kargo_durumu

    if mevcut_durum in [KargoDurumEnum.HAZIRLANIYOR, KargoDurumEnum.PAKETLENDI, KargoDurumEnum.KURYE_TESLIM_HAZIR, KargoDurumEnum.MUSTERIDEN_ALINMAYI_BEKLIYOR]:
        # Kurye kargoyu fiziksel olarak teslim aldığında
        gecerli_sonraki_durumlar = [KargoDurumEnum.KARGO_ALINDI_MERKEZDE, KargoDurumEnum.DAGITIMDA]
    elif mevcut_durum == KargoDurumEnum.KARGO_ALINDI_MERKEZDE:
        gecerli_sonraki_durumlar = [KargoDurumEnum.DAGITIMDA]
    elif mevcut_durum == KargoDurumEnum.DAGITIMDA:
        gecerli_sonraki_durumlar = [
            KargoDurumEnum.TESLIM_EDILDI, 
            KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI,
            KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI,
            KargoDurumEnum.IADE_SURECINDE # Kurye iade sürecini başlatabilir
        ]
    elif mevcut_durum in [KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI, KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI]:
        # Teslim edilemeyen kargolar için kurye iade sürecini başlatabilir
        gecerli_sonraki_durumlar = [KargoDurumEnum.IADE_SURECINDE]
    # Nihai durumlarda (TESLIM_EDILDI, IADE_EDILDI_ISLETMEYE, IPTAL_*) gecerli_sonraki_durumlar boş kalır.

    if request.method == 'POST':
        yeni_durum_str = request.form.get('yeni_kargo_durumu_kurye')
        ozel_not_kurye = request.form.get('ozel_not_kurye', '').strip() # Kurye notunu al, boşsa boş string

        if not yeni_durum_str:
            flash("Lütfen yeni bir kargo durumu seçin.", "error")
        else:
            try:
                yeni_durum_enum = KargoDurumEnum(yeni_durum_str)
                
                if not gecerli_sonraki_durumlar and kargo.kargo_durumu not in [KargoDurumEnum.TESLIM_EDILDI, KargoDurumEnum.IADE_EDILDI_ISLETMEYE]:
                     flash(f"Kargonun mevcut durumu ({kargo.kargo_durumu.value}) üzerinden şu anda bir sonraki adıma geçilemez.", "warning")
                elif yeni_durum_enum not in gecerli_sonraki_durumlar and gecerli_sonraki_durumlar:
                    flash(f"'{yeni_durum_enum.value}' durumu mevcut durum ({kargo.kargo_durumu.value}) için geçerli bir sonraki adım değil.", "warning")
                elif kargo.kargo_durumu == yeni_durum_enum: # Zaten o durumda ise (veya geçiş yoksa)
                    flash("Kargo zaten bu durumda veya geçersiz bir işlem denendi.", "info")
                else: 
                    eski_durum_value = kargo.kargo_durumu.value
                    kargo.kargo_durumu = yeni_durum_enum
                    
                    # Kurye notunu güncelle (mevcut notun üzerine yazmak yerine, belki bir log tutulabilir veya eklenir)
                    # Şimdilik, eğer kurye bir not girdiyse, kargonun özel notunu güncelleyelim.
                    # Eğer işletme notu ile kurye notunu ayırmak isterseniz, Kargo modeline yeni bir alan eklenmeli.
                    if ozel_not_kurye: # Sadece kurye not girdiyse güncelle
                        kargo.ozel_not = ozel_not_kurye

                    if yeni_durum_enum == KargoDurumEnum.TESLIM_EDILDI:
                        kargo.teslim_tarihi = datetime.now()
                        if kargo.odeme_yontemi_teslimde == "Kapıda Nakit":
                            kargo.odeme_durumu_alici = "Alıcıdan Nakit Tahsil Edildi (Kurye)"
                        # Diğer kapıda ödeme durumları (örn: Kurye POS) burada ele alınabilir.
                    
                    db.session.commit()

                    # İşletmeye bildirim
                    if kargo.isletme:
                        create_notification(
                            user_type='isletme', user_id=kargo.isletme_id,
                            message=f"{kargo.takip_numarasi} nolu kargonuzun durumu kurye tarafından '{yeni_durum_enum.value}' olarak güncellendi.",
                            link_endpoint='bp_business.shipment_details', link_params={'kargo_id': kargo.id},
                            bildirim_tipi='kargo_durum_kurye_guncellemesi'
                        )
                    
                    # Adminlere bildirim
                    admin_users = AdminKullanicilar.query.all()
                    for admin in admin_users:
                        create_notification(
                            user_type='admin', user_id=admin.id,
                            message=f"Kurye {session.get('kurye_ad_soyad', '')}, {kargo.takip_numarasi} nolu kargonun durumunu '{eski_durum_value}' -> '{yeni_durum_enum.value}' olarak güncelledi.",
                            link_endpoint='bp_admin.shipment_details', link_params={'kargo_id': kargo.id},
                            bildirim_tipi='kargo_durum_kurye_guncellemesi_admin'
                        )
                    try:
                        db.session.commit() 
                    except Exception as e_notif:
                        db.session.rollback()
                        current_app.logger.error(f"Kurye durum güncelleme bildirimi kaydedilemedi: {e_notif}", exc_info=True)

                    flash(f"'{kargo.takip_numarasi}' numaralı kargonun durumu '{yeni_durum_enum.value}' olarak başarıyla güncellendi.", 'success')
                    return redirect(url_for('bp_courier.dashboard'))

            except ValueError:
                flash("Geçersiz durum seçimi yapıldı.", "error")
            except Exception as e:
                db.session.rollback()
                flash(f"Durum güncellenirken bir hata oluştu: {str(e)}", "error")
                current_app.logger.error(f"Kurye kargo durum güncelleme hatası (Kargo ID: {kargo_id}): {e}", exc_info=True)
    
    return render_template('courier_shipment_action.html', 
                           kargo=kargo, 
                           kurye_guncellenebilir_durumlar=gecerli_sonraki_durumlar,
                           KargoDurumEnum=KargoDurumEnum)
