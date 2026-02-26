# app/routes_common.py
from flask import (
    Blueprint, render_template, flash, session, Response,
    redirect, url_for, current_app, send_file, request, jsonify
)
from .models import (
    Kargolar, Isletmeler, IsletmeOdemeleri, 
    OdemeKargoIliskileri, Bildirimler, KargoDurumEnum, AdminKullanicilar 
)
from . import db
from .utils import normalize_to_e164_tr, create_notification 
from weasyprint import HTML, CSS
from decimal import Decimal
import io
import base64
from datetime import datetime
import re

from barcode import Code128
from barcode.writer import ImageWriter
from .utils import generate_reset_token, verify_reset_token, send_email_notification
from werkzeug.security import generate_password_hash

bp_common = Blueprint('bp_common', __name__, template_folder='templates')


# --- ANA SAYFA YÖNLENDİRMESİ ---
@bp_common.route('/')
def index():
    if 'admin_id' in session:
        return redirect(url_for('bp_admin.dashboard'))
    elif 'isletme_id' in session:
        return redirect(url_for('bp_business.dashboard'))
    elif 'kurye_id' in session:
        return redirect(url_for('bp_courier.dashboard'))
    
    return render_template('landing_page.html')


# === BİLDİRİM ROUTE'LARI ===
@bp_common.route('/notifications')
def view_all_notifications():
    if 'admin_id' not in session and 'isletme_id' not in session and 'kurye_id' not in session:
        flash("Bildirimleri görmek için giriş yapmalısınız.", "error")
        return redirect(url_for('bp_common.index')) 

    page = request.args.get('page', 1, type=int)
    per_page = 15 
    notifications_paginated = None
    user_dashboard_url = url_for('bp_common.index')

    try:
        user_id = None
        query_filter = None
        if 'admin_id' in session:
            user_id = session['admin_id']
            query_filter = Bildirimler.admin_id == user_id
            user_dashboard_url = url_for('bp_admin.dashboard')
        elif 'isletme_id' in session:
            user_id = session['isletme_id']
            query_filter = Bildirimler.isletme_id == user_id
            user_dashboard_url = url_for('bp_business.dashboard')
        elif 'kurye_id' in session:
            user_id = session['kurye_id']
            query_filter = Bildirimler.kurye_id == user_id
            user_dashboard_url = url_for('bp_courier.dashboard')
        
        if user_id:
            notifications_paginated = Bildirimler.query.filter(
                query_filter
            ).order_by(
                Bildirimler.olusturulma_tarihi.desc()
            ).paginate(page=page, per_page=per_page, error_out=False)
        else:
             return redirect(user_dashboard_url)

    except Exception as e:
        current_app.logger.error(f"Bildirimler çekilirken veritabanı hatası: {e}", exc_info=True)
        flash("Bildirimler yüklenirken bir hata oluştu.", "error")
        return redirect(user_dashboard_url)

    return render_template('notifications.html', notifications_paginated=notifications_paginated)

@bp_common.route('/mark_notification_read/<int:notification_id>', methods=['POST'])
def mark_notification_read(notification_id):
    user_id = None
    user_filter = None

    if 'admin_id' in session:
        user_id = session['admin_id']
        user_filter = Bildirimler.admin_id == user_id
    elif 'isletme_id' in session:
        user_id = session['isletme_id']
        user_filter = Bildirimler.isletme_id == user_id
    elif 'kurye_id' in session:
        user_id = session['kurye_id']
        user_filter = Bildirimler.kurye_id == user_id
    else:
        return jsonify(success=False, message="Yetkisiz erişim."), 403

    notification_to_mark = None
    try:
        if user_id:
            notification_to_mark = Bildirimler.query.filter(
                Bildirimler.id == notification_id,
                user_filter
            ).first()

        if notification_to_mark:
            if not notification_to_mark.okundu_mu:
                notification_to_mark.okundu_mu = True
                db.session.commit()
            return jsonify(success=True, message="Bildirim okundu olarak işaretlendi.")
        else:
            return jsonify(success=False, message="Bildirim bulunamadı veya bu bildirimi okuma yetkiniz yok."), 404
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Bildirim (ID: {notification_id}) okundu olarak işaretlenirken hata: {e}", exc_info=True)
        return jsonify(success=False, message="Bildirim işaretlenirken bir sunucu hatası oluştu."), 500

@bp_common.route('/notifications/mark_all_read', methods=['POST'])
def mark_all_notifications_read():
    user_id = None
    user_filter = None
    if 'admin_id' in session:
        user_id = session['admin_id']
        user_filter = Bildirimler.admin_id == user_id
    elif 'isletme_id' in session:
        user_id = session['isletme_id']
        user_filter = Bildirimler.isletme_id == user_id
    elif 'kurye_id' in session:
        user_id = session['kurye_id']
        user_filter = Bildirimler.kurye_id == user_id
    else:
        return jsonify(success=False, message="Yetkisiz erişim."), 403

    if not user_id: 
        return jsonify(success=False, message="Kullanıcı bulunamadı."), 400
        
    try:
        updated_count = Bildirimler.query.filter(user_filter, Bildirimler.okundu_mu == False).update({'okundu_mu': True})
        db.session.commit()
        return jsonify(success=True, message=f"{updated_count} bildirim okundu olarak işaretlendi.")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Tüm bildirimler okundu olarak işaretlenirken hata (Kullanıcı ID: {user_id}): {e}", exc_info=True)
        return jsonify(success=False, message="Bildirimler işaretlenirken bir sunucu hatası oluştu."), 500

@bp_common.route('/notifications/delete_all', methods=['POST'])
def delete_all_notifications():
    user_id = None
    user_filter = None
    if 'admin_id' in session:
        user_id = session['admin_id']
        user_filter = Bildirimler.admin_id == user_id
    elif 'isletme_id' in session:
        user_id = session['isletme_id']
        user_filter = Bildirimler.isletme_id == user_id
    elif 'kurye_id' in session:
        user_id = session['kurye_id']
        user_filter = Bildirimler.kurye_id == user_id
    else:
        return jsonify(success=False, message="Yetkisiz erişim."), 403
    
    if not user_id:
        return jsonify(success=False, message="Kullanıcı bulunamadı."), 400

    try:
        deleted_count = Bildirimler.query.filter(user_filter).delete()
        db.session.commit()
        return jsonify(success=True, message=f"{deleted_count} bildirim silindi.")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Tüm bildirimler silinirken hata (Kullanıcı ID: {user_id}): {e}", exc_info=True)
        return jsonify(success=False, message="Bildirimler silinirken bir sunucu hatası oluştu."), 500

@bp_common.route('/notifications/unread_count')
def unread_notification_count_api():
    count = 0
    user_id = None
    query_filter = None

    if 'admin_id' in session:
        user_id = session['admin_id']
        query_filter = Bildirimler.admin_id == user_id
    elif 'isletme_id' in session:
        user_id = session['isletme_id']
        query_filter = Bildirimler.isletme_id == user_id
    elif 'kurye_id' in session:
        user_id = session['kurye_id']
        query_filter = Bildirimler.kurye_id == user_id
    else:
        return jsonify(unread_count=0)

    try:
        if user_id:
            count = Bildirimler.query.filter(query_filter, Bildirimler.okundu_mu == False).count()
    except Exception as e:
        current_app.logger.error(f"Okunmamış bildirim sayısı API'si çekilirken hata: {e}", exc_info=True)
    
    return jsonify(unread_count=count)

@bp_common.route('/track-shipment', methods=['GET', 'POST'])
def track_shipment_public_input():
    kargo = None
    error_message = None
    takip_no_param = request.args.get('takip_no', '').strip() if request.method == 'GET' else request.form.get('takip_no', '').strip()
    alici_telefon_param_form = request.args.get('alici_telefon', '').strip() if request.method == 'GET' else request.form.get('alici_telefon', '').strip()

    if request.method == 'POST':
        if not takip_no_param or not alici_telefon_param_form:
            error_message = "Lütfen takip numaranızı ve kayıtlı alıcı telefon numaranızı girin."
        else:
            kargo_db = Kargolar.query.filter_by(takip_numarasi=takip_no_param).first()
            if not kargo_db:
                error_message = f"'{takip_no_param}' takip numaralı kargo bulunamadı."
            else:
                normalized_form_phone = normalize_to_e164_tr(alici_telefon_param_form)
                db_phone = kargo_db.alici_telefon 

                if normalized_form_phone and db_phone and normalized_form_phone == db_phone:
                    kargo = kargo_db
                else:
                    error_message = f"Girdiğiniz bilgilerle eşleşen bir kargo kaydı bulunamadı. Lütfen bilgilerinizi kontrol edin."
                    if not normalized_form_phone:
                         current_app.logger.warning(f"Halka açık takip: Girilen telefon ({alici_telefon_param_form}) normalleştirilemedi. Takip No: {takip_no_param}")
        
        return render_template('public_track_input.html', kargo=kargo, error_message=error_message, takip_no_param=takip_no_param, alici_telefon_param=alici_telefon_param_form, KargoDurumEnum=KargoDurumEnum)

    if takip_no_param and not alici_telefon_param_form: 
        error_message = "Lütfen alıcı telefon numarasını da girerek sorgulama yapın."
    
    return render_template('public_track_input.html', kargo=kargo, error_message=error_message, takip_no_param=takip_no_param, alici_telefon_param=alici_telefon_param_form, KargoDurumEnum=KargoDurumEnum)


@bp_common.route('/update-receiver-temporary-location', methods=['POST'])
def update_receiver_temporary_location():
    data = request.get_json()
    if not data:
        return jsonify(success=False, message="Geçersiz istek verisi."), 400

    takip_no = data.get('takip_no')
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    if not takip_no or latitude is None or longitude is None:
        return jsonify(success=False, message="Eksik bilgi: Takip no, enlem veya boylam."), 400

    try:
        kargo = Kargolar.query.filter_by(takip_numarasi=takip_no).first()
        if not kargo:
            return jsonify(success=False, message="Kargo bulunamadı."), 404

        if kargo.kargo_durumu != KargoDurumEnum.DAGITIMDA: 
            return jsonify(success=False, message=f"Kargo şu anda dağıtımda olmadığı için (Durum: {kargo.kargo_durumu.value}) geçici konum paylaşılamaz."), 403

        kargo.alici_gecici_enlem = float(latitude)
        kargo.alici_gecici_boylam = float(longitude)
        kargo.alici_gecici_konum_zamani = datetime.now()
        
        db.session.commit()
        
        return jsonify(success=True, message="Geçici teslimat konumu başarıyla kaydedildi.")
    except ValueError: 
        db.session.rollback()
        return jsonify(success=False, message="Geçersiz enlem/boylam formatı."), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Alıcı geçici konumu güncellenirken hata (Takip No: {takip_no}): {e}", exc_info=True)
        return jsonify(success=False, message="Sunucu hatası, konum güncellenemedi."), 500


@bp_common.route('/generate_barcode_img/<path:data_to_encode>')
def generate_barcode_img_route(data_to_encode):
    try:
        options = {
            'module_height': 15.0, 
            'font_size': 10,       
            'text_distance': 3.0,  
            'quiet_zone': 2.0      
        }
        my_barcode = Code128(data_to_encode, writer=ImageWriter())
        img_byte_arr = io.BytesIO()
        my_barcode.write(img_byte_arr, options=options)
        img_byte_arr.seek(0)
        return send_file(img_byte_arr, mimetype='image/png')
    except Exception as e:
        current_app.logger.error(f"Çizgili barkod üretilirken hata: {str(e)} - Veri: {data_to_encode}", exc_info=True)
        return "Barkod üretilemedi", 500


@bp_common.route('/shipment_pdf/<int:kargo_id>')
def generate_shipment_pdf(kargo_id):
    kargo = None
    user_role = None
    if 'admin_id' in session:
        kargo = Kargolar.query.get_or_404(kargo_id)
        user_role = 'admin'
    elif 'isletme_id' in session:
        kargo = Kargolar.query.filter_by(id=kargo_id, isletme_id=session['isletme_id']).first_or_404()
        user_role = 'isletme'
    else:
        flash("Bu işlemi yapmak için giriş yapmalısınız.", "error")
        return redirect(url_for('bp_common.index'))

    if not kargo: 
        flash("Kargo bulunamadı veya bu kargoyu görüntüleme yetkiniz yok.", "error")
        if user_role == 'admin': return redirect(url_for('bp_admin.all_shipments'))
        if user_role == 'isletme': return redirect(url_for('bp_business.dashboard'))
        return redirect(url_for('bp_common.index'))

    barcode_img_base64 = None
    try:
        options_pdf = {
            'module_height': 12.0, 'module_width': 0.4,
            'font_size': 7, 'text_distance': 3.5,
            'quiet_zone': 1.5,
        }
        my_barcode_pdf = Code128(kargo.takip_numarasi, writer=ImageWriter())
        img_byte_arr_pdf = io.BytesIO()
        my_barcode_pdf.write(img_byte_arr_pdf, options=options_pdf)
        barcode_img_base64 = base64.b64encode(img_byte_arr_pdf.getvalue()).decode('utf-8')
    except Exception as e_barcode:
        current_app.logger.error(f"PDF için barkod üretilirken hata (Kargo ID: {kargo_id}): {e_barcode}", exc_info=True)

    try:
        html_out = render_template('shipment_a5_pdf.html', kargo=kargo, barcode_image_base64=barcode_img_base64)
        pdf_bytes = HTML(string=html_out).write_pdf()
        response = Response(pdf_bytes, mimetype='application/pdf')
        response.headers['Content-Disposition'] = f'inline; filename=kargo_bilgi_fisi_{kargo.takip_numarasi}.pdf'
        return response
    except Exception as e:
        current_app.logger.error(f"Kargo Bilgi Fişi PDF oluşturulurken hata (Kargo ID: {kargo_id}): {str(e)}", exc_info=True)
        flash(f"PDF oluşturulurken bir hata oluştu. Sistem yöneticisine başvurun.", "error")
        if user_role == 'admin': return redirect(url_for('bp_admin.shipment_details', kargo_id=kargo_id))
        if user_role == 'isletme': return redirect(url_for('bp_business.shipment_details', kargo_id=kargo_id))
        return redirect(url_for('bp_common.index'))

@bp_common.route('/payment_statement_pdf/<int:odeme_id>')
def generate_payment_statement_pdf(odeme_id):
    if 'admin_id' not in session: 
        flash("Bu işlemi yapmak için admin olarak giriş yapmalısınız.", "error")
        return redirect(url_for('bp_admin.login'))

    odeme_obj = None 
    try:
        odeme_obj = IsletmeOdemeleri.query.get_or_404(odeme_id)
        isletme_obj = Isletmeler.query.get_or_404(odeme_obj.isletme_id)

        iliskili_kargolar_verisi = []
        kargolar_iliskili_db = Kargolar.query.join(
            OdemeKargoIliskileri, Kargolar.id == OdemeKargoIliskileri.kargo_id
        ).filter(
            OdemeKargoIliskileri.odeme_id == odeme_id
        ).order_by(Kargolar.olusturulma_tarihi.asc()).all()

        for kargo_db_item in kargolar_iliskili_db:
            net_etki_bu_kargo_icin = kargo_db_item.isletmeye_aktarilacak_tutar - kargo_db_item.kargo_ucreti_isletme_borcu
            iliskili_kargolar_verisi.append({
                'kargo': kargo_db_item,
                'net_etki': net_etki_bu_kargo_icin
            })

        html_out = render_template('admin_payment_statement_pdf.html',
                                   odeme_kaydi=odeme_obj,
                                   isletme=isletme_obj,
                                   iliskili_kargolar_data=iliskili_kargolar_verisi,
                                   now=datetime.now) 
        
        pdf_bytes = HTML(string=html_out).write_pdf()
        response = Response(pdf_bytes, mimetype='application/pdf')
        response.headers['Content-Disposition'] = f'inline; filename=odeme_ekstresi_{isletme_obj.isletme_kodu}_{odeme_obj.id}.pdf'
        return response

    except Exception as e:
        current_app.logger.error(f"Ödeme ekstresi PDF (ID: {odeme_id}) oluşturulurken hata: {str(e)}", exc_info=True)
        flash(f"Ödeme ekstresi PDF'i oluşturulurken bir hata oluştu.", "error")
        if odeme_obj and hasattr(odeme_obj, 'isletme_id'): 
             return redirect(url_for('bp_admin.business_payment_history', isletme_id=odeme_obj.isletme_id))
        return redirect(url_for('bp_admin.isletme_bakiyeleri'))


@bp_common.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user_type = request.form.get('user_type') # 'admin', 'isletme' veya 'kurye'

        # Kullanıcıyı veritabanında ara
        user = None
        if user_type == 'admin':
            user = AdminKullanicilar.query.filter_by(email=email).first()
        elif user_type == 'isletme':
            user = Isletmeler.query.filter_by(isletme_email=email).first()
        elif user_type == 'kurye':
            user = Kuryeler.query.filter_by(email=email).first()

        if user:
            token = generate_reset_token(email, user_type)
            reset_url = url_for('bp_common.reset_password', token=token, _external=True)
            
            # E-posta gönder (Şablonu bir sonraki adımda oluşturacağız)
            send_email_notification(
                recipient_email=email,
                subject="Şifre Sıfırlama İsteği",
                template_name="password_reset_mail",
                reset_url=reset_url,
                user_name=getattr(user, 'isletme_adi', getattr(user, 'ad_soyad', user.kullanici_adi))
            )
            flash("Şifre sıfırlama bağlantısı e-posta adresinize gönderildi.", "success")
            return redirect(url_for('bp_common.index'))
        else:
            flash("Bu e-posta adresiyle kayıtlı bir kullanıcı bulunamadı.", "error")

    return render_template('forgot_password.html')

@bp_common.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    data = verify_reset_token(token)
    if not data:
        flash("Sıfırlama bağlantısı geçersiz veya süresi dolmuş.", "error")
        return redirect(url_for('bp_common.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('password')
        
        # --- GÜÇLÜ ŞİFRE KONTROLÜ (YENİ) ---
        # 1. Uzunluk kontrolü
        if len(new_password) < 8:
            flash("Şifre en az 8 karakter uzunluğunda olmalıdır.", "error")
            return render_template('reset_password_form.html', token=token)
        
        # 2. Karmaşıklık kontrolü (Büyük harf, küçük harf ve rakam)
        if not re.search(r"[a-z]", new_password) or \
           not re.search(r"[A-Z]", new_password) or \
           not re.search(r"[0-9]", new_password):
            flash("Şifreniz en az bir büyük harf, bir küçük harf ve bir rakam içermelidir.", "error")
            return render_template('reset_password_form.html', token=token)
        # ----------------------------------

        email = data['email']
        user_type = data['user_type']

        user = None
        if user_type == 'admin':
            user = AdminKullanicilar.query.filter_by(email=email).first()
        elif user_type == 'isletme':
            user = Isletmeler.query.filter_by(isletme_email=email).first()
        elif user_type == 'kurye':
            user = Kuryeler.query.filter_by(email=email).first()

        if user:
            user.set_password(new_password)
            db.session.commit()
            flash("Şifreniz başarıyla güncellendi. Yeni şifrenizle giriş yapabilirsiniz.", "success")
            return redirect(url_for('bp_common.index'))
        else:
            flash("Kullanıcı bulunamadı.", "error")
            return redirect(url_for('bp_common.forgot_password'))

    return render_template('reset_password_form.html', token=token)

# --- YENİ EKLENEN CARİ HESAP EKSTRESİ PDF ROUTE'U ---
@bp_common.route('/business_statement_pdf/<int:isletme_id>')
def generate_business_statement_pdf(isletme_id):
    # Bu raporu hem Admin hem de o işletmenin kendisi indirebilsin
    if 'admin_id' not in session and 'isletme_id' not in session:
        flash("Bu işlemi yapmak için giriş yapmalısınız.", "error")
        return redirect(url_for('bp_common.index'))

    # Eğer bir işletme girdiyse, sadece KENDİ hesabını indirebilir, başkasınınkini indiremez
    if 'isletme_id' in session and session['isletme_id'] != isletme_id:
        flash("Sadece kendi hesap ekstrenizi indirebilirsiniz.", "error")
        return redirect(url_for('bp_business.dashboard'))

    try:
        isletme = Isletmeler.query.get_or_404(isletme_id)

        # İstenirse tarih aralığı filtrelemesi
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        kargolar_query = Kargolar.query.filter(Kargolar.isletme_id == isletme_id, Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI)
        odemeler_query = IsletmeOdemeleri.query.filter_by(isletme_id=isletme_id)

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            kargolar_query = kargolar_query.filter(Kargolar.teslim_tarihi >= datetime.combine(start_date, datetime.min.time()))
            odemeler_query = odemeler_query.filter(IsletmeOdemeleri.odeme_tarihi >= start_date)
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            kargolar_query = kargolar_query.filter(Kargolar.teslim_tarihi <= datetime.combine(end_date, datetime.max.time()))
            odemeler_query = odemeler_query.filter(IsletmeOdemeleri.odeme_tarihi <= end_date)

        kargolar = kargolar_query.all()
        odemeler = odemeler_query.all()

        hareketler = []
        
        # 1. Kargo Teslimatlarını (İşletmenin kazancı ve hizmet borcu) listeye ekle
        for k in kargolar:
            hareketler.append({
                'tarih': k.teslim_tarihi or k.olusturulma_tarihi,
                'islem': f'Kargo Teslimatı (Takip No: {k.takip_numarasi})',
                'alacak': k.isletmeye_aktarilacak_tutar,
                'borc': k.kargo_ucreti_isletme_borcu,
            })
            
        # 2. Ödemeleri (Senin işletmeye yaptığın nakit/havale çıkışı) listeye ekle
        for o in odemeler:
            hareketler.append({
                'tarih': datetime.combine(o.odeme_tarihi, datetime.min.time()),
                'islem': f'Firmamızdan Ödeme/Mahsup İşlemi (Ref: {o.islem_referansi or o.id})',
                'alacak': Decimal('0.00'),
                'borc': o.odenen_tutar, # Bu tutar işletmenin içerideki bakiyesini düşürür
            })

        # İşlemleri tarihe göre eskiden yeniye sırala
        hareketler.sort(key=lambda x: x['tarih'])

        # Kümülatif bakiyeyi (satır satır) hesapla
        bakiye = Decimal('0.00')
        toplam_alacak = Decimal('0.00')
        toplam_borc = Decimal('0.00')

        for h in hareketler:
            toplam_alacak += h['alacak']
            toplam_borc += h['borc']
            bakiye += (h['alacak'] - h['borc'])
            h['bakiye'] = bakiye

        # Logo resminin linkini şablona göndermek için hazırla
        logo_url = url_for('static', filename='images/bee.png', _external=True)

        html_out = render_template(
            'business_statement_pdf.html',
            isletme=isletme,
            hareketler=hareketler,
            toplam_alacak=toplam_alacak,
            toplam_borc=toplam_borc,
            son_bakiye=bakiye,
            now=datetime.now(),
            start_date=start_date_str,
            end_date=end_date_str,
            logo_url=logo_url
        )

        pdf_bytes = HTML(string=html_out).write_pdf()
        response = Response(pdf_bytes, mimetype='application/pdf')
        filename = f"{isletme.isletme_kodu}_Cari_Ekstre_{datetime.now().strftime('%d_%m_%Y')}.pdf"
        response.headers['Content-Disposition'] = f'inline; filename={filename}'
        return response
    


    except Exception as e:
        current_app.logger.error(f"Cari Ekstre PDF (İşletme ID: {isletme_id}) oluşturulurken hata: {str(e)}", exc_info=True)
        flash(f"Ekstre oluşturulurken bir hata oluştu.", "error")
        if 'admin_id' in session:
            return redirect(url_for('bp_admin.isletme_bakiyeleri'))
        return redirect(url_for('bp_business.dashboard'))