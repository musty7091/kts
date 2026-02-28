from app import db
from app.models import Ayarlar, Isletmeler, Kuryeler, Kargolar, KargoDurumEnum
from decimal import Decimal
from datetime import datetime, timedelta


def seed_test_data():
    ayar = Ayarlar.query.filter_by(ayar_adi="sabit_kargo_hizmet_bedeli").first()
    if not ayar:
        ayar = Ayarlar(
            ayar_adi="sabit_kargo_hizmet_bedeli",
            ayar_degeri="100.00",
            aciklama="Test için varsayılan sabit kargo hizmet bedeli",
        )
        db.session.add(ayar)

    isletmeler_data = [
        {
            "isletme_adi": "Lefkoşa Express Market",
            "yetkili_kisi": "Ahmet Demir",
            "isletme_telefon": "+905338880001",
            "isletme_email": "lefkosamarket@example.com",
            "isletme_adres": "Lefkoşa Merkez, KKTC",
            "kullanici_adi": "lefkosamarket",
            "sifre": "Test123!",
            "isletme_kodu": "LXM",
        },
        {
            "isletme_adi": "Girne Hızlı Teslim",
            "yetkili_kisi": "Mehmet Kaya",
            "isletme_telefon": "+905338880002",
            "isletme_email": "girnehizli@example.com",
            "isletme_adres": "Girne Merkez, KKTC",
            "kullanici_adi": "girnehizli",
            "sifre": "Test123!",
            "isletme_kodu": "GHT",
        },
        {
            "isletme_adi": "Mağusa Paket Noktası",
            "yetkili_kisi": "Ayşe Yıldız",
            "isletme_telefon": "+905338880003",
            "isletme_email": "magusapaket@example.com",
            "isletme_adres": "Mağusa, KKTC",
            "kullanici_adi": "magusapaket",
            "sifre": "Test123!",
            "isletme_kodu": "MPN",
        },
        {
            "isletme_adi": "Güzelyurt Mini Lojistik",
            "yetkili_kisi": "Zeynep Arslan",
            "isletme_telefon": "+905338880004",
            "isletme_email": "guzelyurtlojistik@example.com",
            "isletme_adres": "Güzelyurt, KKTC",
            "kullanici_adi": "guzelyurtlojistik",
            "sifre": "Test123!",
            "isletme_kodu": "GML",
        },
    ]

    olusan_isletmeler = []
    for item in isletmeler_data:
        mevcut = Isletmeler.query.filter_by(kullanici_adi=item["kullanici_adi"]).first()
        if mevcut:
            olusan_isletmeler.append(mevcut)
            continue

        yeni = Isletmeler(
            isletme_adi=item["isletme_adi"],
            yetkili_kisi=item["yetkili_kisi"],
            isletme_telefon=item["isletme_telefon"],
            isletme_email=item["isletme_email"],
            isletme_adres=item["isletme_adres"],
            kullanici_adi=item["kullanici_adi"],
            isletme_kodu=item["isletme_kodu"],
            son_kargo_no=0,
            aktif_mi=True,
        )
        yeni.set_password(item["sifre"])
        db.session.add(yeni)
        olusan_isletmeler.append(yeni)

    kuryeler_data = [
        {
            "ad_soyad": "Ali Koçer",
            "kullanici_adi": "kurye1",
            "telefon": "+905338990001",
            "email": "kurye1@example.com",
            "sifre": "Test123!",
        },
        {
            "ad_soyad": "Hasan Taş",
            "kullanici_adi": "kurye2",
            "telefon": "+905338990002",
            "email": "kurye2@example.com",
            "sifre": "Test123!",
        },
        {
            "ad_soyad": "Selim Özer",
            "kullanici_adi": "kurye3",
            "telefon": "+905338990003",
            "email": "kurye3@example.com",
            "sifre": "Test123!",
        },
        {
            "ad_soyad": "Murat Aydın",
            "kullanici_adi": "kurye4",
            "telefon": "+905338990004",
            "email": "kurye4@example.com",
            "sifre": "Test123!",
        },
    ]

    olusan_kuryeler = []
    for item in kuryeler_data:
        mevcut = Kuryeler.query.filter_by(kullanici_adi=item["kullanici_adi"]).first()
        if mevcut:
            olusan_kuryeler.append(mevcut)
            continue

        yeni = Kuryeler(
            ad_soyad=item["ad_soyad"],
            kullanici_adi=item["kullanici_adi"],
            telefon=item["telefon"],
            email=item["email"],
            aktif_mi=True,
        )
        yeni.set_password(item["sifre"])
        db.session.add(yeni)
        olusan_kuryeler.append(yeni)

    db.session.commit()

    ornek_alicilar = [
        ("Mustafa Karaca", "+905331110001", "mustafa1@example.com", "Lefkoşa Surlariçi No:1", "Lefkoşa", "Hamitköy"),
        ("Esra Karadeniz", "+905331110002", "esra2@example.com", "Girne Merkez No:5", "Girne", "Karaoğlanoğlu"),
        ("Mehmet Yılmaz", "+905331110003", "mehmet3@example.com", "Mağusa Çarşı No:12", "Gazimağusa", "Tuzla"),
        ("Ayşe Demir", "+905331110004", "ayse4@example.com", "Güzelyurt Çevre Yolu No:8", "Güzelyurt", "Merkez"),
        ("Ali Can", "+905331110005", "ali5@example.com", "İskele Sahil No:3", "İskele", "Merkez"),
        ("Fatma Kurt", "+905331110006", "fatma6@example.com", "Lefke Cadde No:10", "Lefke", "Merkez"),
    ]

    durumlar = [
        KargoDurumEnum.HAZIRLANIYOR,
        KargoDurumEnum.PAKETLENDI,
        KargoDurumEnum.KURYE_TESLIM_HAZIR,
        KargoDurumEnum.KARGO_ALINDI_MERKEZDE,
        KargoDurumEnum.DAGITIMDA,
        KargoDurumEnum.TESLIM_EDILDI,
    ]

    odeme_yontemleri = [
        "Kapıda Nakit",
        "Kapıda Kredi Kartı",
        "Online / Havale",
    ]

    eklenen_kargo_sayisi = 0

    for idx, isletme in enumerate(olusan_isletmeler, start=1):
        for j in range(3):
            isletme.son_kargo_no = (isletme.son_kargo_no or 0) + 1
            takip_no = f"{isletme.isletme_kodu}-{str(isletme.son_kargo_no).zfill(6)}"

            mevcut_kargo = Kargolar.query.filter_by(takip_numarasi=takip_no).first()
            if mevcut_kargo:
                continue

            alici = ornek_alicilar[(idx + j - 1) % len(ornek_alicilar)]
            durum = durumlar[(idx + j - 1) % len(durumlar)]
            odeme_yontemi = odeme_yontemleri[(idx + j - 1) % len(odeme_yontemleri)]
            kurye = olusan_kuryeler[(idx + j - 1) % len(olusan_kuryeler)]

            urun_bedeli = Decimal("250.00") + Decimal(str((idx + j) * 50))
            kargo_ucreti_alici = Decimal("50.00")
            standart_hizmet_bedeli = Decimal("100.00")

            if odeme_yontemi == "Kapıda Nakit":
                isletmeye_aktarilacak_tutar = urun_bedeli
                kargo_ucreti_isletme_borcu = max(Decimal("0.00"), standart_hizmet_bedeli - kargo_ucreti_alici)
                odeme_durumu_alici = "Alıcıdan Ödeme Bekleniyor"
            elif odeme_yontemi == "Kapıda Kredi Kartı":
                isletmeye_aktarilacak_tutar = Decimal("0.00")
                kargo_ucreti_isletme_borcu = standart_hizmet_bedeli
                odeme_durumu_alici = "Alıcıdan Tahsil Edildi (İşletme KK)"
            else:
                isletmeye_aktarilacak_tutar = Decimal("0.00")
                kargo_ucreti_isletme_borcu = standart_hizmet_bedeli
                odeme_durumu_alici = "Online/Havale Ödendi"

            teslim_tarihi = None
            if durum == KargoDurumEnum.TESLIM_EDILDI:
                teslim_tarihi = datetime.now() - timedelta(days=(j + 1))

            yeni_kargo = Kargolar(
                isletme_id=isletme.id,
                takip_numarasi=takip_no,
                alici_adi_soyadi=alici[0],
                alici_telefon=alici[1],
                alici_email=alici[2],
                alici_adres=alici[3],
                alici_sehir=alici[4],
                alici_ilce=alici[5],
                urun_bedeli_alici_tahsil=urun_bedeli,
                kargo_ucreti_isletme_borcu=kargo_ucreti_isletme_borcu,
                kargo_ucreti_alici_tahsil=kargo_ucreti_alici,
                toplam_tahsil_edilecek_alici=urun_bedeli + kargo_ucreti_alici,
                isletmeye_aktarilacak_tutar=isletmeye_aktarilacak_tutar,
                odeme_yontemi_teslimde=odeme_yontemi,
                odeme_durumu_alici=odeme_durumu_alici,
                kargo_durumu=durum,
                ozel_not="Test amaçlı örnek kayıt",
                isletmeye_aktarildi_mi=False,
                kurye_id=kurye.id,
                teslim_tarihi=teslim_tarihi,
            )

            db.session.add(yeni_kargo)
            eklenen_kargo_sayisi += 1

    db.session.commit()

    print("Örnek veri yükleme tamamlandı.")
    print(f"İşletme sayısı: {Isletmeler.query.count()}")
    print(f"Kurye sayısı: {Kuryeler.query.count()}")
    print(f"Kargo sayısı: {Kargolar.query.count()}")
    print(f"Bu çalıştırmada eklenen yeni kargo sayısı: {eklenen_kargo_sayisi}")


seed_test_data()
