# app/routes_admin.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from .models import (
    AdminKullanicilar, Isletmeler, Kargolar, Ayarlar, 
    IsletmeOdemeleri, OdemeKargoIliskileri, Bildirimler, KargoDurumEnum, Kuryeler
)
from . import db
from .utils import create_notification, calculate_business_earnings, normalize_to_e164_tr
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from sqlalchemy import func, or_
import re 

bp_admin = Blueprint('bp_admin', __name__, template_folder='templates', url_prefix='/admin')

# --- Diğer route fonksiyonları burada yer alıyor (login, dashboard, logout, add_business, edit_business vb.) ---
# Bu fonksiyonlar önceki yanıtlarda verildiği gibi kalacak.
# Sadece 'settings' fonksiyonu güncellenecek.

@bp_admin.route('/login', methods=['GET', 'POST'])
def login():
    if 'admin_id' in session:
        return redirect(url_for('bp_admin.dashboard'))
    if request.method == 'POST':
        kullanici_adi = request.form.get('kullanici_adi')
        sifre = request.form.get('sifre')
        admin = AdminKullanicilar.query.filter_by(kullanici_adi=kullanici_adi).first()
        if admin and check_password_hash(admin.sifre_hash, sifre):
            session['admin_id'] = admin.id
            session['admin_kullanici_adi'] = admin.kullanici_adi
            flash('Giriş başarılı!', 'success')
            return redirect(url_for('bp_admin.dashboard'))
        else:
            flash('Kullanıcı adı veya şifre hatalı.', 'error')
            return redirect(url_for('bp_admin.login'))
    return render_template('login.html')


@bp_admin.route('/dashboard')
def dashboard():
    if 'admin_id' not in session:
        flash('Bu sayfayı görüntülemek için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))

    isletmeler_listesi = []
    query = Isletmeler.query.filter_by(aktif_mi=True)

    search_term = request.args.get('q_isletme', '').strip()
    if search_term:
        query = query.filter(
            or_(
                Isletmeler.isletme_adi.ilike(f"%{search_term}%"),
                Isletmeler.isletme_kodu.ilike(f"%{search_term}%")
            )
        )
    try:
        tum_isletmeler_db = query.order_by(Isletmeler.isletme_adi).all()
        for isletme_obj in tum_isletmeler_db:
            isletme_kazanci_dashboard = calculate_business_earnings(isletme_obj.id)
            isletmeler_listesi.append({
                'isletme_detay': isletme_obj,
                'toplam_kazanc': isletme_kazanci_dashboard
            })
    except Exception as e:
        flash(f"İşletmeler listelenirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"Admin dashboard işletme listeleme hatası: {e}", exc_info=True)
        isletmeler_listesi = []

    return render_template('admin_dashboard.html', isletmeler_data=isletmeler_listesi)


@bp_admin.route('/logout')
def logout():
    session.pop('admin_id', None)
    session.pop('admin_kullanici_adi', None)
    flash('Başarıyla çıkış yaptınız.', 'success')
    return redirect(url_for('bp_common.index'))

@bp_admin.route('/add_business', methods=['GET', 'POST'])
def add_business():
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))

    form_data_on_error = {}
    if request.method == 'POST':
        form_data_on_error = request.form
        isletme_adi = request.form.get('isletme_adi')
        isletme_kodu = request.form.get('isletme_kodu', '').upper()
        kullanici_adi = request.form.get('kullanici_adi')
        sifre = request.form.get('sifre')
        isletme_email = request.form.get('isletme_email', '').strip() 
        yetkili_kisi = request.form.get('yetkili_kisi')
        isletme_telefon_form = request.form.get('isletme_telefon', '').strip()
        isletme_adres = request.form.get('isletme_adres')

        if not isletme_telefon_form:
            flash('İşletme Telefon numarası zorunludur.', 'error')
            return render_template('admin_add_business.html', form_data=form_data_on_error)

        normalized_isletme_telefon = normalize_to_e164_tr(isletme_telefon_form)
        if not normalized_isletme_telefon:
            flash('Geçersiz işletme telefon numarası formatı. Lütfen E.164 formatında girin (örn: +905xxxxxxxxx).', 'error')
            return render_template('admin_add_business.html', form_data=form_data_on_error)

        if not all([isletme_adi, isletme_kodu, kullanici_adi, sifre, isletme_email]):
            flash('İşletme Adı, İşletme Kodu, Kullanıcı Adı, Şifre ve İşletme Email alanları zorunludur.', 'error')
            return render_template('admin_add_business.html', form_data=form_data_on_error)

        if Isletmeler.query.filter_by(isletme_kodu=isletme_kodu).first():
            flash(f"'{isletme_kodu}' işletme kodu zaten kullanılıyor.", 'error')
            return render_template('admin_add_business.html', form_data=form_data_on_error)
        if Isletmeler.query.filter_by(kullanici_adi=kullanici_adi).first():
            flash(f"'{kullanici_adi}' kullanıcı adı zaten kullanılıyor.", 'error')
            return render_template('admin_add_business.html', form_data=form_data_on_error)
        if Isletmeler.query.filter_by(isletme_email=isletme_email).first(): 
            flash(f"'{isletme_email}' e-posta adresi zaten kullanılıyor.", 'error')
            return render_template('admin_add_business.html', form_data=form_data_on_error)
        
        if Isletmeler.query.filter_by(isletme_telefon=normalized_isletme_telefon).first():
            flash(f"'{normalized_isletme_telefon}' telefon numarası zaten başka bir işletme tarafından kullanılıyor.", "error")
            return render_template('admin_add_business.html', form_data=form_data_on_error)

        hashed_sifre = generate_password_hash(sifre)
        yeni_isletme = Isletmeler(
            isletme_adi=isletme_adi, isletme_kodu=isletme_kodu, kullanici_adi=kullanici_adi,
            sifre_hash=hashed_sifre, yetkili_kisi=yetkili_kisi, 
            isletme_telefon=normalized_isletme_telefon, 
            isletme_email=isletme_email, isletme_adres=isletme_adres
        )
        try:
            db.session.add(yeni_isletme)
            db.session.commit()
            flash(f"'{isletme_adi}' adlı işletme başarıyla eklendi!", 'success')
            return redirect(url_for('bp_admin.dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f"İşletme eklenirken bir veritabanı hatası oluştu: {str(e)}", 'error')
            current_app.logger.error(f"İşletme ekleme hatası (DB): {e}", exc_info=True)
            return render_template('admin_add_business.html', form_data=form_data_on_error)

    return render_template('admin_add_business.html', form_data=form_data_on_error)


@bp_admin.route('/edit_business/<int:isletme_id>', methods=['GET', 'POST'])
def edit_business(isletme_id):
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    isletme_to_edit = Isletmeler.query.get_or_404(isletme_id)

    if request.method == 'POST':
        original_email = isletme_to_edit.isletme_email
        new_email = request.form.get('isletme_email', '').strip()
        original_telefon = isletme_to_edit.isletme_telefon
        new_telefon_form = request.form.get('isletme_telefon', '').strip()

        isletme_to_edit.isletme_adi = request.form.get('isletme_adi')
        isletme_to_edit.yetkili_kisi = request.form.get('yetkili_kisi')
        isletme_to_edit.isletme_adres = request.form.get('isletme_adres')
        aktif_mi_form = request.form.get('aktif_mi')
        isletme_to_edit.aktif_mi = True if aktif_mi_form == 'True' else False

        if not new_telefon_form:
            flash('İşletme Telefon numarası zorunludur.', 'error')
            return render_template('admin_edit_business.html', isletme=isletme_to_edit)
        
        normalized_new_telefon = normalize_to_e164_tr(new_telefon_form)
        if not normalized_new_telefon:
            flash('Geçersiz işletme telefon numarası formatı. Lütfen E.164 formatında girin (örn: +905xxxxxxxxx).', 'error')
            return render_template('admin_edit_business.html', isletme=isletme_to_edit)

        if not all([isletme_to_edit.isletme_adi, new_email]):
            flash('İşletme Adı ve İşletme Email alanları zorunludur.', 'error')
            return render_template('admin_edit_business.html', isletme=isletme_to_edit)

        if new_email != original_email:
            existing_isletme_by_email = Isletmeler.query.filter(Isletmeler.id != isletme_id, Isletmeler.isletme_email == new_email).first()
            if existing_isletme_by_email:
                flash(f"'{new_email}' e-posta adresi zaten başka bir işletme tarafından kullanılıyor.", 'error')
                return render_template('admin_edit_business.html', isletme=isletme_to_edit)
        isletme_to_edit.isletme_email = new_email
        
        if normalized_new_telefon != original_telefon:
            existing_isletme_by_phone = Isletmeler.query.filter(Isletmeler.id != isletme_id, Isletmeler.isletme_telefon == normalized_new_telefon).first()
            if existing_isletme_by_phone:
                flash(f"'{normalized_new_telefon}' telefon numarası zaten başka bir işletme tarafından kullanılıyor.", 'error')
                return render_template('admin_edit_business.html', isletme=isletme_to_edit)
        isletme_to_edit.isletme_telefon = normalized_new_telefon

        try:
            db.session.commit()
            flash(f"'{isletme_to_edit.isletme_adi}' adlı işletme bilgileri başarıyla güncellendi!", 'success')
            return redirect(url_for('bp_admin.dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f"İşletme güncellenirken bir hata oluştu: {str(e)}", 'error')
            current_app.logger.error(f"İşletme güncelleme hatası: {e}", exc_info=True)
            return render_template('admin_edit_business.html', isletme=isletme_to_edit)

    return render_template('admin_edit_business.html', isletme=isletme_to_edit)

@bp_admin.route('/add_courier', methods=['GET', 'POST'])
def add_courier():
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    
    form_data_on_error = {}
    if request.method == 'POST':
        form_data_on_error = request.form
        ad_soyad = request.form.get('ad_soyad')
        kullanici_adi = request.form.get('kullanici_adi')
        sifre = request.form.get('sifre')
        sifre_tekrar = request.form.get('sifre_tekrar')
        telefon_form = request.form.get('telefon', '').strip()
        email = request.form.get('email', '').strip() 
        aktif_mi_str = request.form.get('aktif_mi', 'True')
        aktif_mi = True if aktif_mi_str == 'True' else False

        if not telefon_form:
            flash('Kurye Telefon numarası zorunludur.', 'error')
            return render_template('admin_add_courier.html', form_data=form_data_on_error)

        normalized_telefon = normalize_to_e164_tr(telefon_form)
        if not normalized_telefon:
            flash('Geçersiz kurye telefon numarası formatı. Lütfen E.164 formatında girin (örn: +905xxxxxxxxx).', 'error')
            return render_template('admin_add_courier.html', form_data=form_data_on_error)

        if not all([ad_soyad, kullanici_adi, sifre, sifre_tekrar]):
            flash('Ad Soyad, Kullanıcı Adı ve Şifre alanları zorunludur.', 'error')
            return render_template('admin_add_courier.html', form_data=form_data_on_error)

        if sifre != sifre_tekrar:
            flash('Girilen şifreler eşleşmiyor.', 'error')
            return render_template('admin_add_courier.html', form_data=form_data_on_error)
        
        if Kuryeler.query.filter_by(kullanici_adi=kullanici_adi).first():
            flash(f"'{kullanici_adi}' kullanıcı adı zaten kullanılıyor.", 'error')
            return render_template('admin_add_courier.html', form_data=form_data_on_error)
        
        if email and Kuryeler.query.filter(Kuryeler.email != None, Kuryeler.email == email).first():
            flash(f"'{email}' e-posta adresi zaten başka bir kurye tarafından kullanılıyor.", 'error')
            return render_template('admin_add_courier.html', form_data=form_data_on_error)
        
        if Kuryeler.query.filter_by(telefon=normalized_telefon).first():
            flash(f"'{normalized_telefon}' telefon numarası zaten başka bir kurye tarafından kullanılıyor.", 'error')
            return render_template('admin_add_courier.html', form_data=form_data_on_error)

        yeni_kurye = Kuryeler(
            ad_soyad=ad_soyad,
            kullanici_adi=kullanici_adi,
            telefon=normalized_telefon,
            email=email if email else None, 
            aktif_mi=aktif_mi
        )
        yeni_kurye.set_password(sifre) 
        
        try:
            db.session.add(yeni_kurye)
            db.session.commit()
            flash(f"'{ad_soyad}' adlı kurye başarıyla eklendi.", "success")
            return redirect(url_for('bp_admin.list_couriers'))
        except Exception as e:
            db.session.rollback()
            flash(f"Kurye eklenirken bir hata oluştu: {str(e)}", "error")
            current_app.logger.error(f"Kurye ekleme hatası: {e}", exc_info=True)
            return render_template('admin_add_courier.html', form_data=form_data_on_error)
            
    return render_template('admin_add_courier.html', form_data=form_data_on_error)

@bp_admin.route('/couriers')
def list_couriers():
    if 'admin_id' not in session:
        flash('Bu sayfayı görüntülemek için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    
    try:
        kuryeler = Kuryeler.query.order_by(Kuryeler.aktif_mi.desc(), Kuryeler.ad_soyad).all()
    except Exception as e:
        flash("Kuryeler listelenirken bir hata oluştu.", "error")
        current_app.logger.error(f"Kurye listeleme hatası: {e}", exc_info=True)
        kuryeler = []
    return render_template('admin_list_couriers.html', kuryeler=kuryeler)

@bp_admin.route('/edit_courier/<int:kurye_id>', methods=['GET', 'POST'])
def edit_courier(kurye_id):
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    
    kurye_to_edit = Kuryeler.query.get_or_404(kurye_id)
    form_data_on_error = {} 

    if request.method == 'POST':
        form_data_on_error = request.form 
        kurye_to_edit.ad_soyad = request.form.get('ad_soyad', kurye_to_edit.ad_soyad)
        new_telefon_form = request.form.get('telefon', '').strip()
        original_telefon = kurye_to_edit.telefon
        new_email = request.form.get('email', '').strip()
        original_email = kurye_to_edit.email
        aktif_mi_str = request.form.get('aktif_mi', str(kurye_to_edit.aktif_mi))
        kurye_to_edit.aktif_mi = True if aktif_mi_str == 'True' else False

        yeni_sifre = request.form.get('yeni_sifre')
        yeni_sifre_tekrar = request.form.get('yeni_sifre_tekrar')

        if not new_telefon_form:
            flash('Kurye Telefon numarası zorunludur.', 'error')
            return render_template('admin_edit_courier.html', kurye=kurye_to_edit, form_data=form_data_on_error)

        normalized_new_telefon = normalize_to_e164_tr(new_telefon_form)
        if not normalized_new_telefon:
            flash('Geçersiz kurye telefon numarası formatı. Lütfen E.164 formatında girin (örn: +905xxxxxxxxx).', 'error')
            return render_template('admin_edit_courier.html', kurye=kurye_to_edit, form_data=form_data_on_error)
        
        if new_email and new_email != original_email and Kuryeler.query.filter(Kuryeler.id != kurye_id, Kuryeler.email == new_email).first():
            flash(f"'{new_email}' e-posta adresi zaten başka bir kurye tarafından kullanılıyor.", 'error')
            return render_template('admin_edit_courier.html', kurye=kurye_to_edit, form_data=form_data_on_error)
        kurye_to_edit.email = new_email if new_email else None
        
        if normalized_new_telefon != original_telefon and Kuryeler.query.filter(Kuryeler.id != kurye_id, Kuryeler.telefon == normalized_new_telefon).first():
            flash(f"'{normalized_new_telefon}' telefon numarası zaten başka bir kurye tarafından kullanılıyor.", 'error')
            return render_template('admin_edit_courier.html', kurye=kurye_to_edit, form_data=form_data_on_error)
        kurye_to_edit.telefon = normalized_new_telefon

        if yeni_sifre: 
            if yeni_sifre != yeni_sifre_tekrar:
                flash('Yeni girilen şifreler eşleşmiyor.', 'error')
                return render_template('admin_edit_courier.html', kurye=kurye_to_edit, form_data=form_data_on_error)
            kurye_to_edit.set_password(yeni_sifre)
            flash('Kurye şifresi başarıyla güncellendi.', 'info')

        try:
            db.session.commit()
            flash(f"'{kurye_to_edit.ad_soyad}' adlı kuryenin bilgileri başarıyla güncellendi.", "success")
            return redirect(url_for('bp_admin.list_couriers'))
        except Exception as e:
            db.session.rollback()
            flash(f"Kurye bilgileri güncellenirken bir hata oluştu: {str(e)}", "error")
            current_app.logger.error(f"Kurye düzenleme hatası (ID: {kurye_id}): {e}", exc_info=True)
            # Hata durumunda, güncellenmeye çalışılan kurye nesnesi ve form verileriyle template'i tekrar render et
            return render_template('admin_edit_courier.html', kurye=kurye_to_edit, form_data=form_data_on_error)

    # GET request için form_data'yı kurye bilgileriyle doldur
    # Bu, POST hatası olmadığında veya sayfa ilk yüklendiğinde çalışır.
    # Eğer request.form doluysa (yani POST sonrası bir hata ile gelinmişse), o değerler kullanılır.
    # Değilse, kurye nesnesinden gelen değerler kullanılır.
    get_form_data = {
        'ad_soyad': kurye_to_edit.ad_soyad,
        'telefon': kurye_to_edit.telefon,
        'email': kurye_to_edit.email or '', # None ise boş string
        'aktif_mi': str(kurye_to_edit.aktif_mi) # String'e çevir
    }
    return render_template('admin_edit_courier.html', kurye=kurye_to_edit, form_data=get_form_data)

@bp_admin.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için admin olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))

    current_admin_user = AdminKullanicilar.query.get(session['admin_id'])
    if not current_admin_user: 
        flash('Admin kullanıcı bilgileri bulunamadı. Lütfen tekrar giriş yapın.', 'error')
        session.pop('admin_id', None)
        session.pop('admin_kullanici_adi', None)
        return redirect(url_for('bp_admin.login'))

    def get_settings_dict():
        ayarlar_s = {}
        try:
            ayar_isimleri = ['sabit_kargo_hizmet_bedeli'] 
            for ayar_adi_filter in ayar_isimleri:
                ayar_db = Ayarlar.query.filter_by(ayar_adi=ayar_adi_filter).first()
                if ayar_db:
                    ayarlar_s[ayar_db.ayar_adi] = ayar_db
        except Exception as e:
            current_app.logger.error(f"Ayarlar getirme hatası: {e}", exc_info=True)
        return ayarlar_s

    password_form_data = {} # Şifre formu için hata durumunda verileri tutar

    if request.method == 'POST':
        action = request.form.get('action') 

        if action == 'update_system_settings':
            try:
                sabit_kargo_ucreti_form = request.form.get('sabit_kargo_hizmet_bedeli')
                kargo_ucret_ayari = Ayarlar.query.filter_by(ayar_adi='sabit_kargo_hizmet_bedeli').first()
                if kargo_ucret_ayari and sabit_kargo_ucreti_form is not None:
                    try:
                        deger = Decimal(sabit_kargo_ucreti_form.replace(',', '.'))
                        if deger < 0:
                            raise InvalidOperation("Kargo ücreti negatif olamaz.")
                        kargo_ucret_ayari.ayar_degeri = str(deger)
                        kargo_ucret_ayari.guncellenme_tarihi = datetime.now()
                    except InvalidOperation:
                        flash("Geçersiz sabit kargo ücreti formatı! Pozitif bir sayı girin (örn: 100.00).", "error")
                        # Hata durumunda, şifre formu verilerini de koruyarak render et
                        return render_template('admin_settings.html', ayarlar=get_settings_dict(), current_admin=current_admin_user, password_form_data=password_form_data)
                
                db.session.commit()
                flash('Sistem ayarları başarıyla güncellendi.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"Sistem ayarları güncellenirken bir hata oluştu: {str(e)}", 'error')
                current_app.logger.error(f"Sistem ayarları güncelleme hatası: {e}", exc_info=True)
            # Sistem ayarları güncellendikten sonra sayfayı tekrar render et (şifre formu verileriyle birlikte)
            return render_template('admin_settings.html', ayarlar=get_settings_dict(), current_admin=current_admin_user, password_form_data=password_form_data)


        elif action == 'change_admin_password':
            password_form_data = request.form # Form verilerini al
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_new_password = request.form.get('confirm_new_password')

            if not all([current_password, new_password, confirm_new_password]):
                flash('Lütfen tüm şifre alanlarını doldurun.', 'danger')
            elif not check_password_hash(current_admin_user.sifre_hash, current_password):
                flash('Mevcut şifreniz yanlış.', 'danger')
            elif new_password != confirm_new_password:
                flash('Yeni şifreler eşleşmiyor.', 'danger')
                # Sadece current_password'ı koru, yeni şifre alanlarını temizle
                password_form_data = {'current_password': current_password} 
            else:
                errors = []
                if len(new_password) < 8: 
                    errors.append("Yeni şifre en az 8 karakter olmalıdır.")
                # Diğer şifre karmaşıklığı kuralları buraya eklenebilir (büyük harf, küçük harf, rakam, özel karakter vb.)

                if errors:
                    for error_msg in errors:
                        flash(error_msg, 'danger')
                    # Hatalı durumda current_password'ı koru
                    password_form_data = {'current_password': current_password}
                else:
                    try:
                        current_admin_user.sifre_hash = generate_password_hash(new_password)
                        db.session.commit()
                        # Şifre başarıyla değiştirildi, oturumu sonlandır ve giriş sayfasına yönlendir
                        session.pop('admin_id', None)
                        session.pop('admin_kullanici_adi', None)
                        flash('Admin şifreniz başarıyla güncellendi! Güvenlik nedeniyle tekrar giriş yapmanız gerekmektedir.', 'success')
                        return redirect(url_for('bp_admin.login')) 
                    except Exception as e:
                        db.session.rollback()
                        flash(f'Admin şifresi güncellenirken bir hata oluştu: {str(e)}', 'error')
                        current_app.logger.error(f"Admin şifre güncelleme hatası (Admin ID: {current_admin_user.id}): {e}", exc_info=True)
                        # Hata durumunda current_password'ı koru
                        password_form_data = {'current_password': current_password} 
            
            # Şifre formuyla ilgili bir işlem yapıldıysa (başarılı veya hatalı), sayfayı tekrar render et
            # password_form_data, hatalı girişlerde veya başarılı olmayan denemelerde alanları dolu tutar.
            return render_template('admin_settings.html', ayarlar=get_settings_dict(), current_admin=current_admin_user, password_form_data=password_form_data)

    # GET request için veya form gönderimi yoksa
    ayarlar_dict = get_settings_dict()
    return render_template('admin_settings.html', ayarlar=ayarlar_dict, current_admin=current_admin_user, password_form_data=password_form_data)

# --- Diğer admin route'ları (all_shipments, update_shipment_status, assign_courier, reports, vb.) burada devam eder ---
# Bu fonksiyonlar önceki yanıtlarda verildiği gibi kalacak.
@bp_admin.route('/all_shipments')
def all_shipments():
    if 'admin_id' not in session:
        flash('Bu sayfayı görüntülemek için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))

    query = Kargolar.query.join(Isletmeler)
    
    takip_no_search = request.args.get('takip_no', '').strip()
    isletme_adi_search = request.args.get('isletme_adi', '').strip()
    alici_adi_search = request.args.get('alici_adi', '').strip()
    alici_telefon_search = request.args.get('alici_telefon', '').strip()
    kargo_durumu_filter_str = request.args.get('kargo_durumu', '')
    baslangic_tarihi_str = request.args.get('baslangic_tarihi', '')
    bitis_tarihi_str = request.args.get('bitis_tarihi', '')

    if takip_no_search:
        query = query.filter(Kargolar.takip_numarasi.ilike(f"%{takip_no_search}%"))
    if isletme_adi_search:
        query = query.filter(
            or_(
                Isletmeler.isletme_adi.ilike(f"%{isletme_adi_search}%"),
                Isletmeler.isletme_kodu.ilike(f"%{isletme_adi_search}%")
            )
        )
    if alici_adi_search:
        query = query.filter(Kargolar.alici_adi_soyadi.ilike(f"%{alici_adi_search}%"))
    if alici_telefon_search:
        query = query.filter(Kargolar.alici_telefon.ilike(f"%{alici_telefon_search}%"))
    
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
        tum_kargolar = query.order_by(Kargolar.olusturulma_tarihi.desc()).all()
    except Exception as e:
        flash(f"Kargolar listelenirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"Tüm kargolar listeleme hatası: {e}", exc_info=True)
        tum_kargolar = []
        
    return render_template('admin_all_shipments.html', kargolar=tum_kargolar, KargoDurumEnum=KargoDurumEnum)

@bp_admin.route('/update_shipment_status/<int:kargo_id>', methods=['GET', 'POST'])
def update_shipment_status(kargo_id):
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için admin olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    kargo = Kargolar.query.get_or_404(kargo_id)
    
    admin_guncellenebilir_durumlar = [
        KargoDurumEnum.KARGO_ALINDI_MERKEZDE, 
        KargoDurumEnum.DAGITIMDA, 
        KargoDurumEnum.TESLIM_EDILDI,
        KargoDurumEnum.TESLIM_EDILEMEDI_ALICI_ULASILAMADI, 
        KargoDurumEnum.TESLIM_EDILEMEDI_ADRES_HATALI,
        KargoDurumEnum.IADE_SURECINDE, 
        KargoDurumEnum.IADE_EDILDI_ISLETMEYE,
        KargoDurumEnum.IPTAL_EDILDI_ADMIN
    ]
    
    form_data_on_error = {}
    if request.method == 'POST':
        form_data_on_error = request.form
        yeni_durum_str = request.form.get('yeni_kargo_durumu')
        
        if yeni_durum_str:
            try:
                yeni_durum_enum = KargoDurumEnum(yeni_durum_str)
                if yeni_durum_enum in admin_guncellenebilir_durumlar:
                    kargo.kargo_durumu = yeni_durum_enum
                    if yeni_durum_enum == KargoDurumEnum.TESLIM_EDILDI and kargo.teslim_tarihi is None:
                        kargo.teslim_tarihi = datetime.now()

                    if yeni_durum_enum == KargoDurumEnum.TESLIM_EDILDI:
                        if kargo.odeme_yontemi_teslimde == "Kapıda Nakit":
                            kargo.odeme_durumu_alici = "Alıcıdan Nakit Tahsil Edildi"
                        elif kargo.odeme_yontemi_teslimde == "Kapıda Kredi Kartı":
                             kargo.odeme_durumu_alici = "Alıcıdan Tahsil Edildi (İşletme KK)"
                        
                    db.session.commit()

                    if kargo.isletme_id:
                        create_notification(
                            user_type='isletme',
                            user_id=kargo.isletme_id,
                            message=f"Takip No: {kargo.takip_numarasi} olan kargonuzun durumu '{yeni_durum_enum.value}' olarak güncellendi.",
                            link_endpoint='bp_business.shipment_details', 
                            link_params={'kargo_id': kargo.id},
                            bildirim_tipi='kargo_durum_guncellemesi'
                        )
                        try:
                            db.session.commit()
                        except Exception as e_notif:
                            db.session.rollback()
                            current_app.logger.error(f"Kargo durum güncelleme bildirimi kaydedilemedi: {e_notif}", exc_info=True)

                    flash(f"'{kargo.takip_numarasi}' takip numaralı kargonun durumu '{yeni_durum_enum.value}' olarak güncellendi.", 'success')
                    return redirect(url_for('bp_admin.all_shipments'))
                else:
                    flash("Seçilen durum admin tarafından güncellenebilir bir durum değil.", 'error')
            except ValueError:
                flash("Geçersiz bir durum değeri seçtiniz.", 'error')
            except Exception as e:
                db.session.rollback()
                flash(f"Durum güncellenirken bir hata oluştu: {str(e)}", 'error')
                current_app.logger.error(f"Kargo durum güncelleme hatası: {e}", exc_info=True)
        else:
            flash("Lütfen yeni bir kargo durumu seçin.", 'error')
        
        return render_template('admin_update_shipment_status.html', kargo=kargo, admin_guncellenebilir_durumlar=admin_guncellenebilir_durumlar, form_data=form_data_on_error)

    return render_template('admin_update_shipment_status.html', kargo=kargo, admin_guncellenebilir_durumlar=admin_guncellenebilir_durumlar, form_data=form_data_on_error)

@bp_admin.route('/scan_shipment_status', methods=['GET', 'POST'])
def scan_shipment_status():
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için admin olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    
    if request.method == 'POST':
        takip_no_scanned = request.form.get('takip_no_scanned', '').strip()
        if not takip_no_scanned:
            flash("Lütfen bir takip numarası okutun veya girin.", "warning")
            return render_template('admin_scan_shipment.html') 

        kargo = Kargolar.query.filter(Kargolar.takip_numarasi.ilike(f"%{takip_no_scanned}%")).first()
        
        if kargo:
            flash(f"'{kargo.takip_numarasi}' numaralı kargo bulundu. Durumunu güncelleyebilirsiniz.", "info")
            return redirect(url_for('bp_admin.update_shipment_status', kargo_id=kargo.id))
        else:
            flash(f"'{takip_no_scanned}' takip numaralı kargo bulunamadı.", "error")
            return render_template('admin_scan_shipment.html', scan_value=takip_no_scanned)
    
    return render_template('admin_scan_shipment.html')

@bp_admin.route('/shipment_details/<int:kargo_id>')
def shipment_details(kargo_id):
    if 'admin_id' not in session:
        flash('Bu sayfayı görüntülemek için admin olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    kargo = Kargolar.query.get_or_404(kargo_id)
    return render_template('shipment_details.html', kargo=kargo, KargoDurumEnum=KargoDurumEnum)

@bp_admin.route('/assign_courier/<int:kargo_id>', methods=['GET', 'POST'])
def assign_courier(kargo_id):
    if 'admin_id' not in session:
        flash('Bu işlemi yapmak için admin olarak giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    
    kargo = Kargolar.query.get_or_404(kargo_id)
    
    non_assignable_final_statuses = [
        KargoDurumEnum.TESLIM_EDILDI,
        KargoDurumEnum.IADE_EDILDI_ISLETMEYE,
        KargoDurumEnum.IPTAL_EDILDI_ADMIN,
        KargoDurumEnum.IPTAL_EDILDI_ISLETME
    ]
    if kargo.kargo_durumu in non_assignable_final_statuses:
        flash(f"Bu kargonun ({kargo.kargo_durumu.value}) durumu kurye atamaya/değiştirmeye uygun değil.", "warning")
        return redirect(url_for('bp_admin.shipment_details', kargo_id=kargo_id))

    if request.method == 'POST':
        selected_kurye_id_str = request.form.get('kurye_id')
        
        if not selected_kurye_id_str or selected_kurye_id_str == "0": 
            if selected_kurye_id_str == "0": 
                if kargo.kurye_id:
                    # eski_kurye_id = kargo.kurye_id # Bu değişkene gerek yok
                    kargo.kurye_id = None
                    db.session.commit()
                    flash(f"'{kargo.takip_numarasi}' numaralı kargonun kurye ataması kaldırıldı.", 'info')
                else:
                    flash('Kargo zaten bir kuryeye atanmamış.', 'info')
                return redirect(url_for('bp_admin.shipment_details', kargo_id=kargo_id))
            else: 
                flash('Lütfen bir kurye seçin veya "Kuryeyi Kaldır" seçeneğini işaretleyin.', 'error')
        else: 
            try:
                kurye_id_int = int(selected_kurye_id_str)
                secilen_kurye = Kuryeler.query.filter_by(id=kurye_id_int, aktif_mi=True).first()
                
                if not secilen_kurye:
                    flash('Seçilen kurye bulunamadı veya aktif değil.', 'error')
                else:
                    kargo.kurye_id = secilen_kurye.id
                    db.session.commit()
                    
                    create_notification(
                        user_type='kurye',
                        user_id=secilen_kurye.id,
                        message=f"Size yeni bir kargo atandı: {kargo.takip_numarasi}. Alıcı: {kargo.alici_adi_soyadi}, Adres: {kargo.alici_adres[:30]}...",
                        link_endpoint='bp_courier.dashboard', 
                        bildirim_tipi='yeni_kargo_atama'
                    )
                    try:
                        db.session.commit()
                    except Exception as e_notif:
                        db.session.rollback()
                        current_app.logger.error(f"Kurye atama bildirimi kaydedilemedi: {e_notif}", exc_info=True)

                    flash(f"'{kargo.takip_numarasi}' numaralı kargo, '{secilen_kurye.ad_soyad}' adlı kuryeye başarıyla atandı.", 'success')
                    return redirect(url_for('bp_admin.shipment_details', kargo_id=kargo_id))
            except ValueError:
                flash('Geçersiz kurye IDsi.', 'error')
            except Exception as e:
                db.session.rollback()
                flash(f"Kurye atanırken bir hata oluştu: {str(e)}", "error")
                current_app.logger.error(f"Kurye atama hatası (Kargo ID: {kargo_id}): {e}", exc_info=True)
        
        aktif_kuryeler = Kuryeler.query.filter_by(aktif_mi=True).order_by(Kuryeler.ad_soyad).all()
        return render_template('admin_assign_courier.html', kargo=kargo, kuryeler=aktif_kuryeler, KargoDurumEnum=KargoDurumEnum)

    aktif_kuryeler = Kuryeler.query.filter_by(aktif_mi=True).order_by(Kuryeler.ad_soyad).all()
    return render_template('admin_assign_courier.html', kargo=kargo, kuryeler=aktif_kuryeler, KargoDurumEnum=KargoDurumEnum)

@bp_admin.route('/reports', methods=['GET', 'POST'])
def reports():
    if 'admin_id' not in session:
        flash('Bu sayfayı görüntülemek için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))

    report_data = None
    start_date_str = request.form.get('start_date') if request.method == 'POST' else request.args.get('start_date')
    end_date_str = request.form.get('end_date') if request.method == 'POST' else request.args.get('end_date')
    
    start_date_obj = None
    end_date_obj = None

    if start_date_str and end_date_str:
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            if start_date_obj > end_date_obj:
                flash('Başlangıç tarihi, bitiş tarihinden sonra olamaz.', 'error')
                report_data = {} # Hata durumunda boş rapor verisi
            else:
                report_data = {'isletme_reports': []}

                report_data['total_shipments_created'] = Kargolar.query.filter(
                    Kargolar.olusturulma_tarihi >= datetime.combine(start_date_obj, datetime.min.time()),
                    Kargolar.olusturulma_tarihi <= datetime.combine(end_date_obj, datetime.max.time())
                ).count()

                teslim_edilmis_kargolar_sorgusu = Kargolar.query.filter(
                    Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI,
                    Kargolar.teslim_tarihi >= datetime.combine(start_date_obj, datetime.min.time()),
                    Kargolar.teslim_tarihi <= datetime.combine(end_date_obj, datetime.max.time())
                )
                report_data['delivered_shipments_count'] = teslim_edilmis_kargolar_sorgusu.count()
                
                toplam_kazanilan_hizmet_bedeli_genel = Decimal('0.00')
                # calculate_business_earnings fonksiyonu zaten bu mantığı içeriyor,
                # ancak burada genel toplam için tekrar hesaplama yapılmış.
                # Bu kısım optimize edilebilir veya olduğu gibi bırakılabilir.
                sabit_kargo_ayari_rpt = Ayarlar.query.filter_by(ayar_adi='sabit_kargo_hizmet_bedeli').first()
                standart_hizmet_bedeli_rpt = Decimal(sabit_kargo_ayari_rpt.ayar_degeri) if sabit_kargo_ayari_rpt and sabit_kargo_ayari_rpt.ayar_degeri else Decimal('100.00')

                for kargo_item_rpt in teslim_edilmis_kargolar_sorgusu.all():
                    if kargo_item_rpt.odeme_yontemi_teslimde == "Kapıda Nakit" and \
                       kargo_item_rpt.kargo_ucreti_isletme_borcu == Decimal('0.00') and \
                       kargo_item_rpt.kargo_ucreti_alici_tahsil >= standart_hizmet_bedeli_rpt:
                        toplam_kazanilan_hizmet_bedeli_genel += standart_hizmet_bedeli_rpt
                    else:
                        toplam_kazanilan_hizmet_bedeli_genel += kargo_item_rpt.kargo_ucreti_isletme_borcu
                report_data['total_service_fee_earned'] = toplam_kazanilan_hizmet_bedeli_genel

                report_data['total_payments_made_to_businesses'] = db.session.query(
                    func.sum(IsletmeOdemeleri.odenen_tutar)
                ).filter(
                    IsletmeOdemeleri.odeme_tarihi >= start_date_obj,
                    IsletmeOdemeleri.odeme_tarihi <= end_date_obj
                ).scalar() or Decimal('0.00')

                isletmeler_rpt = Isletmeler.query.filter_by(aktif_mi=True).order_by(Isletmeler.isletme_adi).all()
                for isletme_rpt in isletmeler_rpt:
                    isletme_total_created_rpt = Kargolar.query.filter(
                        Kargolar.isletme_id == isletme_rpt.id,
                        Kargolar.olusturulma_tarihi >= datetime.combine(start_date_obj, datetime.min.time()),
                        Kargolar.olusturulma_tarihi <= datetime.combine(end_date_obj, datetime.max.time())
                    ).count()
                    
                    isletme_total_delivered_rpt = Kargolar.query.filter(
                        Kargolar.isletme_id == isletme_rpt.id,
                        Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI,
                        Kargolar.teslim_tarihi >= datetime.combine(start_date_obj, datetime.min.time()),
                        Kargolar.teslim_tarihi <= datetime.combine(end_date_obj, datetime.max.time())
                    ).count()
                    
                    isletme_service_fee_earned_hesaplanan_rpt = calculate_business_earnings(
                        isletme_rpt.id,
                        start_date=start_date_obj,
                        end_date=end_date_obj
                    )
                    
                    # Sadece ilgili tarih aralığında aktivitesi olan işletmeleri rapora dahil et
                    if isletme_total_created_rpt > 0 or isletme_total_delivered_rpt > 0 or isletme_service_fee_earned_hesaplanan_rpt > 0:
                        report_data['isletme_reports'].append({
                            'name': isletme_rpt.isletme_adi,
                            'code': isletme_rpt.isletme_kodu,
                            'total_created': isletme_total_created_rpt,
                            'total_delivered': isletme_total_delivered_rpt,
                            'service_fee': isletme_service_fee_earned_hesaplanan_rpt
                        })
        except ValueError:
            flash('Geçersiz tarih formatı. Lütfen २०२२-AA-GG formatında girin.', 'error')
            report_data = {} # Hata durumunda boş rapor verisi
        except Exception as e:
            flash(f'Rapor oluşturulurken bir hata meydana geldi: {str(e)}', 'error')
            current_app.logger.error(f"Raporlama hatası: {e}", exc_info=True)
            report_data = {} # Hata durumunda boş rapor verisi
    
    elif request.method == 'POST' and (not start_date_str or not end_date_str) : # Form gönderildi ama tarihler boş
            flash('Rapor oluşturmak için lütfen başlangıç ve bitiş tarihlerini seçin.', 'warning')
            report_data = {} # Boş rapor verisi

    # Template'e gönderilecek form tarihleri (sayfa yenilendiğinde inputlarda kalması için)
    form_dates_for_template = {
        'start_date': start_date_str if start_date_str else '',
        'end_date': end_date_str if end_date_str else ''
    }
    
    return render_template('admin_reports.html', report_data=report_data, form_dates=form_dates_for_template)

@bp_admin.route('/isletme_bakiyeleri')
def isletme_bakiyeleri():
    if 'admin_id' not in session:
        flash('Bu sayfayı görüntülemek için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))

    isletme_verileri_liste = []
    isletme_query = Isletmeler.query.filter_by(aktif_mi=True)
    search_term = request.args.get('q_bakiye_isletme', '').strip()

    if search_term:
        isletme_query = isletme_query.filter(
            or_(
                Isletmeler.isletme_adi.ilike(f"%{search_term}%"),
                Isletmeler.isletme_kodu.ilike(f"%{search_term}%")
            )
        )
    
    try:
        aktif_isletmeler = isletme_query.order_by(Isletmeler.isletme_adi).all()
        for isletme_obj_bakiye in aktif_isletmeler:
            # İşletmenin brüt alacağı (sadece kapıda nakit ve ürün bedeli olanlardan)
            brut_isletme_alacagi_kargolardan = db.session.query(
                func.sum(Kargolar.isletmeye_aktarilacak_tutar) # Bu zaten ürün bedelini (veya 0'ı) tutuyor
            ).filter(
                Kargolar.isletme_id == isletme_obj_bakiye.id,
                Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI,
                Kargolar.isletmeye_aktarildi_mi == False # Henüz mahsuplaşmamış olanlar
                # Odeme yöntemi kontrolüne gerek yok, isletmeye_aktarilacak_tutar zaten ona göre hesaplanıyor.
            ).scalar() or Decimal('0.00')

            # İşletmenin toplam hizmet bedeli borcu (teslim edilmiş ve mahsuplaşmamış tüm kargolardan)
            toplam_hizmet_bedeli_borcu_isletmenin = db.session.query(
                func.sum(Kargolar.kargo_ucreti_isletme_borcu)
            ).filter(
                Kargolar.isletme_id == isletme_obj_bakiye.id,
                Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI,
                Kargolar.isletmeye_aktarildi_mi == False # Henüz mahsuplaşmamış olanlar
            ).scalar() or Decimal('0.00')
            
            # Daha önce yapılmış ve mahsuplaşmış ödemeler/alacaklar (bunlar bakiyeyi etkilememeli, çünkü kargolar zaten kapatıldı)
            # Bu yüzden net bakiye hesabı sadece 'isletmeye_aktarildi_mi == False' olan kargolar üzerinden yapılmalı.
            # Ancak, genel bir fikir vermesi açısından toplam yapılmış ödemeler de gösterilebilir.
            # Şimdiki mantıkta, `yapilmis_odemeler_toplami` net bakiyeden düşülüyor, bu doğru.
            
            yapilmis_odemeler_toplami = db.session.query(
                func.sum(IsletmeOdemeleri.odenen_tutar)
            ).filter(IsletmeOdemeleri.isletme_id == isletme_obj_bakiye.id).scalar() or Decimal('0.00')

            # Net Bakiye: (Tahsil edilecek ürün bedelleri) - (Kesilecek hizmet bedelleri) - (Daha önce yapılan ödemeler/alacaklar)
            # isletmeye_aktarilacak_tutar: Kapıda nakitte ürün bedeli, diğerlerinde 0.
            # kargo_ucreti_isletme_borcu: Standart hizmet bedeli veya (standart - alıcıdan alınan kargo ücreti)
            # Dolayısıyla, (isletmeye_aktarilacak_tutar - kargo_ucreti_isletme_borcu) her bir kargonun işletmeye net etkisidir.
            # Bu net etkilerin toplamı, işletmenin o anki toplam alacağı/borcudur (henüz mahsuplaşmamış kargolar için).
            
            net_mahsuplasmamis_bakiye = db.session.query(
                func.sum(Kargolar.isletmeye_aktarilacak_tutar - Kargolar.kargo_ucreti_isletme_borcu)
            ).filter(
                Kargolar.isletme_id == isletme_obj_bakiye.id,
                Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI,
                Kargolar.isletmeye_aktarildi_mi == False
            ).scalar() or Decimal('0.00')
            
            # Genel bakiye, mahsuplaşmamış kargoların net etkisi eksi daha önce yapılmış tüm ödemelerdir.
            # Bu mantık biraz karışık olabilir. Belki de `IsletmeOdemeleri` tablosundaki `odenen_tutar`
            # zaten `isletmeye_aktarildi_mi = True` olan kargoların net etkisini yansıtıyordur.
            # Eğer `record_payment` doğru çalışıyorsa, `IsletmeOdemeleri.odenen_tutar` işletmeye yapılan
            # net ödemeyi (veya işletmeden alınan net borcu) gösterir.
            # Bu durumda, işletmenin toplam alacağı/borcu:
            # (Tüm teslim edilmiş kargoların (isletmeye_aktarilacak_tutar - kargo_ucreti_isletme_borcu) toplamı) - (Tüm IsletmeOdemeleri.odenen_tutar toplamı)
            
            tum_kargolarin_net_etkisi = db.session.query(
                 func.sum(Kargolar.isletmeye_aktarilacak_tutar - Kargolar.kargo_ucreti_isletme_borcu)
            ).filter(
                Kargolar.isletme_id == isletme_obj_bakiye.id,
                Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI
            ).scalar() or Decimal('0.00')

            net_bakiye_guncel = tum_kargolarin_net_etkisi - yapilmis_odemeler_toplami

            isletme_verileri_liste.append({
                'isletme': isletme_obj_bakiye,
                'toplam_alacak_veya_borc': net_bakiye_guncel # Güncellenmiş bakiye hesabı
            })
    except Exception as e:
        current_app.logger.error(f"İşletme bakiyeleri getirilirken hata: {str(e)}", exc_info=True)
        flash(f"İşletme bakiyeleri getirilirken bir hata oluştu.", "error")
        isletme_verileri_liste = []

    return render_template('admin_isletme_bakiyeleri.html', isletme_verileri=isletme_verileri_liste)

@bp_admin.route('/record_payment/<int:isletme_id>', methods=['GET', 'POST'])
def record_payment(isletme_id):
        if 'admin_id' not in session:
            flash('Bu işlemi yapmak için admin olarak giriş yapmalısınız.', 'error')
            return redirect(url_for('bp_admin.login'))

        isletme_obj_payment = Isletmeler.query.get_or_404(isletme_id)
        
        mahsuplasacak_kargolar_db = Kargolar.query.filter(
            Kargolar.isletme_id == isletme_id,
            Kargolar.isletmeye_aktarildi_mi == False,
            Kargolar.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI
        ).order_by(Kargolar.olusturulma_tarihi.asc()).all()

        kargolar_data_template = []
        kümülatif_bakiye_satir_icin = Decimal('0.00') 
        for kargo_db_item in mahsuplasacak_kargolar_db:
            isletmenin_alacagi_bu_kargodan_brut = kargo_db_item.isletmeye_aktarilacak_tutar
            isletmenin_borcu_bu_kargodan_hizmet = kargo_db_item.kargo_ucreti_isletme_borcu
            bu_kargonun_kendi_icindeki_net_etkisi = isletmenin_alacagi_bu_kargodan_brut - isletmenin_borcu_bu_kargodan_hizmet
            kümülatif_bakiye_satir_icin += bu_kargonun_kendi_icindeki_net_etkisi # Bu, her satır için artan kümülatif toplamı hesaplar
            
            kargolar_data_template.append({
                'kargo_nesnesi': kargo_db_item,
                'isletme_alacak_gosterilecek': isletmenin_alacagi_bu_kargodan_brut,
                'isletme_borc_gosterilecek': isletmenin_borcu_bu_kargodan_hizmet,
                'kümülatif_bakiye_satirda': kümülatif_bakiye_satir_icin, # BU ANAHTAR EKLENİYOR
                'bu_satirin_net_etkisi_checkbox': bu_kargonun_kendi_icindeki_net_etkisi
            })
        
        today_date_str = date.today().strftime('%Y-%m-%d')

        if request.method == 'POST':
            # ... (POST bloğunun içeriği - burası şimdilik önemli değil, hata GET request'te oluşuyor) ...
            # POST bloğunda hata olsa bile, en alttaki render_template yine yukarıda hesaplanan
            # kargolar_data_template'i kullanır.
            odeme_tarihi_str = request.form.get('odeme_tarihi')
            islem_referansi = request.form.get('islem_referansi')
            secilen_kargo_idler_str = request.form.getlist('kargo_ids')

            if not odeme_tarihi_str:
                flash('Ödeme tarihi zorunludur.', 'error')
                # Hata durumunda template'e secilen_kargo_idler'i de gönderelim ki checkbox'lar korunabilsin
                return render_template('admin_record_payment.html', isletme=isletme_obj_payment, kargolar_data=kargolar_data_template, today_date=today_date_str, secilen_kargo_idler=request.form.getlist('kargo_ids'))
            if not secilen_kargo_idler_str:
                flash('Lütfen mahsuplaşmaya dahil edilecek en az bir kargo seçin.', 'error')
                return render_template('admin_record_payment.html', isletme=isletme_obj_payment, kargolar_data=kargolar_data_template, today_date=today_date_str, secilen_kargo_idler=request.form.getlist('kargo_ids'))

            try:
                odeme_tarihi = datetime.strptime(odeme_tarihi_str, '%Y-%m-%d').date()
                hesaplanan_net_odeme_tutari_islem = Decimal('0.00')
                kapatilacak_kargolar_veritabanindan = []

                for kargo_id_str_payment in secilen_kargo_idler_str:
                    kargo_veritabanindan = Kargolar.query.get(int(kargo_id_str_payment))

                    if not (kargo_veritabanindan and kargo_veritabanindan.isletme_id == isletme_id and \
                            not kargo_veritabanindan.isletmeye_aktarildi_mi and \
                            kargo_veritabanindan.kargo_durumu == KargoDurumEnum.TESLIM_EDILDI):
                        flash(f"Seçilen kargolardan biri (ID: {kargo_id_str_payment}) ödeme/mahsup için artık uygun değil.", "error")
                        return render_template('admin_record_payment.html', isletme=isletme_obj_payment, kargolar_data=kargolar_data_template, today_date=today_date_str, secilen_kargo_idler=request.form.getlist('kargo_ids'))

                    net_etki_bu_kargo_icin = kargo_veritabanindan.isletmeye_aktarilacak_tutar - kargo_veritabanindan.kargo_ucreti_isletme_borcu
                    hesaplanan_net_odeme_tutari_islem += net_etki_bu_kargo_icin
                    kapatilacak_kargolar_veritabanindan.append(kargo_veritabanindan)
                
                yeni_odeme = IsletmeOdemeleri(
                    isletme_id=isletme_id,
                    odeme_tarihi=odeme_tarihi,
                    odenen_tutar=hesaplanan_net_odeme_tutari_islem,
                    aciklama=islem_referansi
                )
                db.session.add(yeni_odeme)
                db.session.flush()
                
                for kargo_db_item_obj_payment in kapatilacak_kargolar_veritabanindan:
                    kargo_db_item_obj_payment.isletmeye_aktarildi_mi = True
                    odeme_kargo_iliskisi = OdemeKargoIliskileri(odeme_id=yeni_odeme.id, kargo_id=kargo_db_item_obj_payment.id)
                    db.session.add(odeme_kargo_iliskisi)
                
                db.session.commit()
                
                create_notification(
                    user_type='isletme',
                    user_id=isletme_id,
                    message=f"Hesabınıza {hesaplanan_net_odeme_tutari_islem:.2f} TL tutarında ödeme/mahsup işlendi. Referans: {yeni_odeme.id}",
                    link_endpoint='bp_business.payment_details',
                    link_params={'odeme_id': yeni_odeme.id},
                    bildirim_tipi='odeme_kaydi'
                )
                try:
                    db.session.commit()
                except Exception as e_notif_payment:
                    db.session.rollback()
                    current_app.logger.error(f"Ödeme kaydı bildirimi kaydedilemedi: {e_notif_payment}", exc_info=True)
                
                if hesaplanan_net_odeme_tutari_islem >= 0:
                    flash_mesaj = f"{isletme_obj_payment.isletme_adi} işletmesine {hesaplanan_net_odeme_tutari_islem:.2f} TL tutarında ödeme/mahsuplaşma başarıyla kaydedildi."
                else:
                    flash_mesaj = f"{isletme_obj_payment.isletme_adi} işletmesinden {-hesaplanan_net_odeme_tutari_islem:.2f} TL tutarında alacak/mahsuplaşma başarıyla kaydedildi."
                flash(flash_mesaj, "success")
                return redirect(url_for('bp_admin.isletme_bakiyeleri'))

            except ValueError:
                flash('Geçersiz tarih formatı. Lütfen २०२२-AA-GG formatında girin.', 'error')
            except Exception as e:
                db.session.rollback()
                flash(f"Ödeme kaydedilirken bir hata oluştu: {str(e)}", 'error')
                current_app.logger.error(f"Ödeme kaydı hatası: {e}", exc_info=True)
            
            # POST içinde bir hata olursa, formu tekrar render et
            return render_template('admin_record_payment.html', isletme=isletme_obj_payment, kargolar_data=kargolar_data_template, today_date=today_date_str, secilen_kargo_idler=request.form.getlist('kargo_ids'))

        # GET request için
        return render_template('admin_record_payment.html', isletme=isletme_obj_payment, kargolar_data=kargolar_data_template, today_date=today_date_str)

@bp_admin.route('/business_payment_history/<int:isletme_id>')
def business_payment_history(isletme_id):
    if 'admin_id' not in session:
        flash('Bu sayfayı görüntülemek için giriş yapmalısınız.', 'error')
        return redirect(url_for('bp_admin.login'))
    
    isletme = Isletmeler.query.get_or_404(isletme_id)
    try:
        odemeler_db = IsletmeOdemeleri.query.filter_by(isletme_id=isletme_id).order_by(IsletmeOdemeleri.odeme_tarihi.desc()).all()
    except Exception as e:
        flash(f"Ödeme geçmişi getirilirken bir hata oluştu: {str(e)}", "error")
        current_app.logger.error(f"İşletme ödeme geçmişi hatası: {e}", exc_info=True)
        odemeler_db = []
        
    return render_template('admin_business_payment_history.html', isletme=isletme, odemeler=odemeler_db)
