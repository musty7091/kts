# app/routes_courier.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from .models import Kuryeler, Kargolar, KargoDurumEnum, AdminKullanicilar
from . import db
from .utils import kurye_required, create_notification
from datetime import datetime

bp_courier = Blueprint('bp_courier', __name__, template_folder='templates/courier', url_prefix='/courier')


@bp_courier.route('/login', methods=['GET', 'POST'])
def login():
    if 'kurye_id' in session:
        return redirect(url_for('bp_courier.dashboard'))

    if request.method == 'POST':
        kullanici_adi = (request.form.get('kullanici_adi') or '').strip()
        sifre = request.form.get('sifre') or ''

        if not kullanici_adi or not sifre:
            flash('Kullanıcı adı ve şifre zorunludur.', 'error')
            return redirect(url_for('bp_courier.login'))

        kurye = Kuryeler.query.filter_by(kullanici_adi=kullanici_adi).first()

        if kurye and kurye.aktif_mi and kurye.check_password(sifre):
            # Güvenlik için temiz başla
            session.clear()
            session.permanent = True

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
@kurye_required
def dashboard():
    # @kurye_required sayesinde manuel session kontrolü kaldırıldı, içerik aynıdır.
    kurye_id = session['kurye_id']
    atanmis_aktif_kargolar = []
    tamamlanmis_kargolar = []

    try:
        # Kuryenin aktif olarak ilgilenmesi gereken kargo durumları
        kurye_aktif_gorev_durumlari = [
            KargoDurumEnum.HAZIRLANIYOR,
            KargoDurumEnum.PAKETLENDI,
            KargoDurumEnum.KURYE_TESLIM_HAZIR,
            KargoDurumEnum.MUSTERIDEN_ALINMAYI_BEKLIYOR,
            KargoDurumEnum.KARGO_ALINDI_MERKEZDE,
            KargoDurumEnum.DAGITIMDA,
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

    return render_template(
        'courier_dashboard.html',
        aktif_kargolar=atanmis_aktif_kargolar,
        tamamlanmis_kargolar=tamamlanmis_kargolar,
        KargoDurumEnum=KargoDurumEnum
    )


@bp_courier.route('/logout')
def logout():
    session.clear()
    flash('Başarıyla çıkış yaptınız.', 'success')
    return redirect(url_for('bp_common.index'))


@bp_courier.route('/shipment_action/<int:kargo_id>', methods=['GET', 'POST'])
@kurye_required
def shipment_action_by_courier(kargo_id):
    kargo = Kargolar.query.filter_by(id=kargo_id, kurye_id=session['kurye_id']).first_or_404()

    # Kargonun mevcut durumuna göre kuryenin seçebileceği bir sonraki mantıksal durumlar
    gecerli_sonraki_durumlar = []
    mevcut_durum = kargo.kargo_durumu

    if mevcut_durum in [
        KargoDurumEnum.HAZIRLANIYOR,
        KargoDurumEnum.PAKETLENDI,
        KargoDurumEnum.KURYE_TESLIM_HAZIR,
        KargoDurumEnum.MUSTERIDEN_ALINMAYI_BEKLIYOR
    ]:
        # Kurye kargoyu fiziksel olarak teslim aldığında
        gecerli_sonraki_durumlar = [KargoDurumEnum.KARGO_ALINDI_MERKEZDE, KargoDurumEnum.DAGITIMDA]

    elif mevcut_durum == KargoDurumEnum.KARGO_ALINDI_MERKEZDE:
        gecerli_sonraki_durumlar = [KargoDurumEnum.DAGITIMDA]

    elif mevcut_durum == KargoDurumEnum.DAGITIMDA:
        gecerli_sonraki_durumlar = [
            KargoDurumEnum.TESLIM_EDILDI,
            KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI,
            KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI,
            KargoDurumEnum.IADE_SURECINDE
        ]

    elif mevcut_durum in [
        KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI,
        KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI
    ]:
        gecerli_sonraki_durumlar = [KargoDurumEnum.IADE_SURECINDE]

    # Nihai durumlarda (TESLIM_EDILDI, IADE_EDILDI_ISLETMEYE, IPTAL_*) gecerli_sonraki_durumlar boş kalır.

    if request.method == 'POST':
        yeni_durum_str = request.form.get('yeni_kargo_durumu_kurye')
        ozel_not_kurye = (request.form.get('ozel_not_kurye') or '').strip()

        if not yeni_durum_str:
            flash("Lütfen yeni bir kargo durumu seçin.", "error")
        else:
            try:
                yeni_durum_enum = KargoDurumEnum(yeni_durum_str)

                if not gecerli_sonraki_durumlar and kargo.kargo_durumu not in [
                    KargoDurumEnum.TESLIM_EDILDI,
                    KargoDurumEnum.IADE_EDILDI_ISLETMEYE
                ]:
                    flash(f"Kargonun mevcut durumu ({kargo.kargo_durumu.value}) üzerinden şu anda bir sonraki adıma geçilemez.", "warning")

                elif gecerli_sonraki_durumlar and yeni_durum_enum not in gecerli_sonraki_durumlar:
                    flash(f"'{yeni_durum_enum.value}' durumu mevcut durum ({kargo.kargo_durumu.value}) için geçerli bir sonraki adım değil.", "warning")

                elif kargo.kargo_durumu == yeni_durum_enum:
                    flash("Kargo zaten bu durumda veya geçersiz bir işlem denendi.", "info")

                else:
                    eski_durum_value = kargo.kargo_durumu.value

                    kargo.kargo_durumu = yeni_durum_enum
                    kargo.guncellenme_tarihi = datetime.now()

                    # Kurye notu: sadece dolu gelirse yaz
                    if ozel_not_kurye:
                        kargo.ozel_not = ozel_not_kurye

                    if yeni_durum_enum == KargoDurumEnum.TESLIM_EDILDI:
                        kargo.teslim_tarihi = datetime.now()
                        if kargo.odeme_yontemi_teslimde == "Kapıda Nakit":
                            kargo.odeme_durumu_alici = "Alıcıdan Nakit Tahsil Edildi (Kurye)"

                    # Önce kargo güncellemesini kaydet
                    db.session.commit()

                    # İşletmeye bildirim
                    if kargo.isletme:
                        try:
                            create_notification(
                                user_type='isletme', user_id=kargo.isletme_id,
                                message=f"{kargo.takip_numarasi} nolu kargonuzun durumu kurye tarafından '{yeni_durum_enum.value}' olarak güncellendi.",
                                link_endpoint='bp_business.shipment_details', link_params={'kargo_id': kargo.id},
                                bildirim_tipi='kargo_durum_kurye_guncellemesi'
                            )
                            db.session.commit()
                        except Exception as e_notif_isletme:
                            db.session.rollback()
                            current_app.logger.error(f"Kurye durum güncelleme işletme bildirimi kaydedilemedi: {e_notif_isletme}", exc_info=True)

                    # Adminlere bildirim
                    try:
                        admin_users = AdminKullanicilar.query.all()
                        for admin in admin_users:
                            create_notification(
                                user_type='admin', user_id=admin.id,
                                message=f"Kurye {session.get('kurye_ad_soyad', '')}, {kargo.takip_numarasi} nolu kargonun durumunu '{eski_durum_value}' -> '{yeni_durum_enum.value}' olarak güncellendi.",
                                link_endpoint='bp_admin.shipment_details', link_params={'kargo_id': kargo.id},
                                bildirim_tipi='kargo_durum_kurye_guncellemesi_admin'
                            )
                        db.session.commit()
                    except Exception as e_notif_admin:
                        db.session.rollback()
                        current_app.logger.error(f"Kurye durum güncelleme admin bildirimi kaydedilemedi: {e_notif_admin}", exc_info=True)

                    flash(f"'{kargo.takip_numarasi}' numaralı kargonun durumu '{yeni_durum_enum.value}' olarak başarıyla güncellendi.", 'success')
                    return redirect(url_for('bp_courier.dashboard'))

            except ValueError:
                flash("Geçersiz durum seçimi yapıldı.", "error")
            except Exception as e:
                db.session.rollback()
                flash(f"Durum güncellenirken bir hata oluştu: {str(e)}", "error")
                current_app.logger.error(f"Kurye kargo durum güncelleme hatası (Kargo ID: {kargo_id}): {e}", exc_info=True)

    return render_template(
        'courier_shipment_action.html',
        kargo=kargo,
        kurye_guncellenebilir_durumlar=gecerli_sonraki_durumlar,
        KargoDurumEnum=KargoDurumEnum
    )