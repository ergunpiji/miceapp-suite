"""
Satın Alma — Veritabanı bağlantısı ve başlangıç verisi (seed)
"""

import json
from datetime import date, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import (
    Base, User, Venue, Customer, Service, CustomCategory, Request, Budget,
    EventType, Settings, OrgTitle, Invoice, EmailTemplate,
    ExpenseReport, ExpenseItem, UndocumentedEntry, FinancialVendor,
    VendorPrepayment, InvoiceLog, PrepaymentRequest, PrepaymentRequestLog,
    _EMAIL_TEMPLATE_DEFAULTS, _uuid, _now,
)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

import os

_raw_url = os.environ.get("DATABASE_URL", "sqlite:///./satinalma.db")

# Railway / Render PostgreSQL URL'i "postgres://" ile başlar,
# SQLAlchemy "postgresql://" ister.
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
_is_sqlite   = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL: stale bağlantıları otomatik yenile (Railway idle timeout)
    _engine_kwargs["pool_pre_ping"]   = True
    _engine_kwargs["pool_recycle"]    = 300   # 5 dk'da bir bağlantıyı yenile
    _engine_kwargs["pool_size"]       = 5
    _engine_kwargs["max_overflow"]    = 10

engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def seed_data() -> None:
    """Veritabanına başlangıç verisi ekler (varsa atlar)"""
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()

    try:
        # ----------------------------------------------------------------
        # 1. Kullanıcılar
        # ----------------------------------------------------------------
        if db.query(User).count() == 0:
            users = [
                User(
                    id=_uuid(),
                    email="admin@miceapp.net",
                    password_hash=pwd_ctx.hash("Admin123"),
                    role="admin",
                    name="Admin",
                    surname="User",
                    title="Sistem Yöneticisi",
                    phone="+90 555 000 0001",
                    active=True,
                    created_at=_now(),
                ),
                User(
                    id=_uuid(),
                    email="manager@miceapp.net",
                    password_hash=pwd_ctx.hash("Manager123"),
                    role="yonetici",
                    name="Proje",
                    surname="Yöneticisi",
                    title="Proje Yöneticisi",
                    phone="+90 555 000 0002",
                    active=True,
                    created_at=_now(),
                ),
                User(
                    id=_uuid(),
                    email="satinalma@miceapp.net",
                    password_hash=pwd_ctx.hash("Satinalma123"),
                    role="satinalma",
                    name="Satın Alma",
                    surname="Kullanıcısı",
                    title="Satın Alma Uzmanı",
                    phone="+90 555 000 0003",
                    active=True,
                    created_at=_now(),
                ),
            ]
            db.add_all(users)
            db.flush()
            print("  [seed] Kullanıcılar eklendi.")

        # ----------------------------------------------------------------
        # 2. Etkinlik Tipleri
        # ----------------------------------------------------------------
        if db.query(EventType).count() == 0:
            event_types = [
                EventType(id=_uuid(), code='yi', label='Yurtiçi Etkinlik',           active=True, sort_order=1),
                EventType(id=_uuid(), code='yd', label='Yurtdışı Etkinlik',           active=True, sort_order=2),
                EventType(id=_uuid(), code='ut', label='Ürün Tanıtım Toplantısı',    active=True, sort_order=3),
                EventType(id=_uuid(), code='tk', label='Kongre Yönetimi',             active=True, sort_order=4),
                EventType(id=_uuid(), code='dk', label='Danışma Kurulu Toplantısı',  active=True, sort_order=5),
            ]
            db.add_all(event_types)
            db.flush()
            print("  [seed] Etkinlik tipleri eklendi.")

        # ----------------------------------------------------------------
        # 3. Müşteriler
        # ----------------------------------------------------------------
        if db.query(Customer).count() == 0:
            customers = [
                Customer(
                    id=_uuid(),
                    name="ABC Teknoloji A.Ş.",
                    code="abc",
                    sector="Teknoloji",
                    address="Maslak Mah. Büyükdere Cad. No:123 Sarıyer/İstanbul",
                    tax_office="Maslak",
                    tax_no="1234567890",
                    email="info@abcteknoloji.com",
                    phone="+90 212 555 0100",
                    notes="VIP müşteri",
                    contacts_json=json.dumps([
                        {"name": "Ayşe Kara",  "title": "Etkinlik Koordinatörü",  "email": "a.kara@abcteknoloji.com",  "phone": "+90 532 111 2233"},
                        {"name": "Mert Doğan", "title": "Genel Müdür Yardımcısı", "email": "m.dogan@abcteknoloji.com", "phone": "+90 532 111 4455"},
                    ], ensure_ascii=False),
                    created_at=_now(),
                ),
                Customer(
                    id=_uuid(),
                    name="XYZ Holding",
                    code="xyz",
                    sector="Finans",
                    address="Levent Mah. Nispetiye Cad. No:45 Beşiktaş/İstanbul",
                    tax_office="Levent",
                    tax_no="9876543210",
                    email="etkinlik@xyzholding.com",
                    phone="+90 212 444 0200",
                    notes="",
                    contacts_json=json.dumps([
                        {"name": "Selin Yıldız", "title": "Kurumsal İletişim Müdürü", "email": "s.yildiz@xyzholding.com", "phone": "+90 541 222 3344"},
                        {"name": "Burak Çelik",  "title": "İdari İşler Uzmanı",       "email": "b.celik@xyzholding.com",  "phone": "+90 541 222 5566"},
                    ], ensure_ascii=False),
                    created_at=_now(),
                ),
                Customer(
                    id=_uuid(),
                    name="DEF İnşaat Ltd. Şti.",
                    code="def",
                    sector="İnşaat",
                    address="Atatürk Cad. No:78 Kadıköy/İstanbul",
                    tax_office="Kadıköy",
                    tax_no="5566778899",
                    email="iletisim@definsaat.com",
                    phone="+90 216 333 0300",
                    notes="Aylık toplantı organizasyonu",
                    contacts_json=json.dumps([
                        {"name": "Hande Arslan", "title": "Proje Müdürü", "email": "h.arslan@definsaat.com",  "phone": "+90 553 333 7788"},
                        {"name": "Tolga Yılmaz", "title": "Genel Müdür",  "email": "t.yilmaz@definsaat.com", "phone": "+90 553 333 9900"},
                    ], ensure_ascii=False),
                    created_at=_now(),
                ),
            ]
            db.add_all(customers)
            db.flush()
            print("  [seed] Müşteriler eklendi.")

        # ----------------------------------------------------------------
        # 3. Tedarikçiler / Mekanlar
        # ----------------------------------------------------------------
        if db.query(Venue).count() == 0:
            venues = [
                Venue(
                    id=_uuid(),
                    name="Hilton İstanbul Bomonti",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul"], ensure_ascii=False),
                    supplier_type="otel",
                    address="Silahşör Cad. No:42 Bomonti, Şişli/İstanbul",
                    stars=5,
                    total_rooms=829,
                    website="https://www.hilton.com",
                    notes="5 yıldızlı lüks otel, büyük konferans kapasitesi",
                    halls_json=json.dumps([
                        {"name": "Grand Ballroom", "capacity": 2000, "area": 2400},
                        {"name": "Bomonti Salonu", "capacity": 500,  "area": 600},
                        {"name": "Toplantı Odası A", "capacity": 50, "area": 80},
                        {"name": "Toplantı Odası B", "capacity": 30, "area": 50},
                    ], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Ahmet Yılmaz", "title": "Etkinlik Koordinatörü",
                         "email": "etkinlik@hiltonbomonti.com", "phone": "+90 212 375 3000"},
                        {"name": "Zeynep Kaya",  "title": "Satış Müdürü",
                         "email": "satis@hiltonbomonti.com", "phone": "+90 212 375 3001"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="İstanbul Marriott Hotel Şişli",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul"], ensure_ascii=False),
                    supplier_type="otel",
                    address="Büyükdere Cad. No:94 Şişli/İstanbul",
                    stars=5,
                    total_rooms=380,
                    website="https://www.marriott.com",
                    notes="Merkezi konumda, iş dünyasına yakın",
                    halls_json=json.dumps([
                        {"name": "Şişli Ballroom", "capacity": 800, "area": 900},
                        {"name": "Executive Lounge", "capacity": 100, "area": 120},
                        {"name": "Boardroom", "capacity": 20, "area": 40},
                    ], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Mehmet Demir", "title": "Event Manager",
                         "email": "events@marriottsisli.com", "phone": "+90 212 371 1500"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="Conrad İstanbul Bosphorus",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul"], ensure_ascii=False),
                    supplier_type="otel",
                    address="Yıldız Cad. No:13 Beşiktaş/İstanbul",
                    stars=5,
                    total_rooms=590,
                    website="https://www.conradistanbul.com",
                    notes="Boğaz manzaralı lüks otel",
                    halls_json=json.dumps([
                        {"name": "Conrad Ballroom", "capacity": 1200, "area": 1400},
                        {"name": "Bosphorus Hall", "capacity": 400, "area": 500},
                        {"name": "Meeting Room 1",  "capacity": 40,  "area": 60},
                        {"name": "Meeting Room 2",  "capacity": 25,  "area": 40},
                    ], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Ayşe Şahin", "title": "Banquet & Events Manager",
                         "email": "events@conradistanbul.com", "phone": "+90 212 310 2525"},
                        {"name": "Caner Öztürk", "title": "Groups Coordinator",
                         "email": "groups@conradistanbul.com", "phone": "+90 212 310 2526"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="ProAV Teknik Ekipman",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul", "Ankara", "İzmir"], ensure_ascii=False),
                    supplier_type="teknik",
                    address="Dudullu OSB Mah. Nato Yolu Cad. No:5 Ümraniye/İstanbul",
                    stars=None,
                    total_rooms=0,
                    website="https://www.proav.com.tr",
                    notes="Ses, ışık, projeksiyon ekipmanı kiralama ve kurulum",
                    halls_json=json.dumps([], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Serkan Arslan", "title": "Teknik Koordinatör",
                         "email": "teknik@proav.com.tr", "phone": "+90 216 450 0101"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="Flash Transfer",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul", "Ankara"], ensure_ascii=False),
                    supplier_type="transfer",
                    address="Atatürk Havalimanı Yanı, Bakırköy/İstanbul",
                    stars=None,
                    total_rooms=0,
                    website="https://www.flashtransfer.com.tr",
                    notes="VIP transfer, kafile transferi, havalimanı karşılama",
                    halls_json=json.dumps([], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Hakan Güneş", "title": "Operasyon Müdürü",
                         "email": "ops@flashtransfer.com.tr", "phone": "+90 212 555 7070"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
            ]
            db.add_all(venues)
            db.flush()
            print("  [seed] Tedarikçiler eklendi.")

        # ----------------------------------------------------------------
        # 4. Hizmet Kataloğu
        # ----------------------------------------------------------------
        if db.query(Service).count() == 0:
            services_data = [
                # Konaklama
                ("accommodation", "Standart Oda SGL (Tek Kişilik)", "Gece"),
                ("accommodation", "Standart Oda DBL (Çift Kişilik)", "Gece"),
                ("accommodation", "Superior Oda SGL", "Gece"),
                ("accommodation", "Superior Oda DBL", "Gece"),
                ("accommodation", "Deluxe Oda", "Gece"),
                ("accommodation", "Suite Oda", "Gece"),
                ("accommodation", "Ekstra Yatak", "Gece"),
                # Toplantı / Salon
                ("meeting", "Salon Kiralama (Tam Gün)", "Salon/Gün"),
                ("meeting", "Salon Kiralama (Yarım Gün)", "Salon/Yarım Gün"),
                ("meeting", "Projeksiyon ve Perde", "Adet/Gün"),
                ("meeting", "Ses Sistemi (Mikrofon Dahil)", "Set/Gün"),
                ("meeting", "LED Ekran (P2.5 veya P3)", "m²/Gün"),
                ("meeting", "Simultane Çeviri Sistemi", "Set/Gün"),
                ("meeting", "Video Kayıt Hizmeti", "Gün"),
                ("meeting", "Canlı Yayın (Streaming)", "Gün"),
                # F&B
                ("fb", "Kahvaltı (Açık Büfe)", "Kişi"),
                ("fb", "Öğle Yemeği (Açık Büfe)", "Kişi"),
                ("fb", "Akşam Yemeği (Açık Büfe)", "Kişi"),
                ("fb", "Gala Yemeği", "Kişi"),
                ("fb", "Coffee Break (Sabah)", "Kişi"),
                ("fb", "Coffee Break (Öğleden Sonra)", "Kişi"),
                ("fb", "Welcome Drink Kokteyli", "Kişi"),
                ("fb", "Set Menü (3 Kurs)", "Kişi"),
                # Teknik
                ("teknik", "Ses Sistemi (Hat Array)", "Set/Gün"),
                ("teknik", "Işık Platformu (Wash + Spot)", "Set/Gün"),
                ("teknik", "Sahne Montajı (Modüler)", "m²"),
                ("teknik", "Projeksiyon (10,000 ANSI Lümen)", "Adet/Gün"),
                ("teknik", "LED Dış Mekan Ekranı", "m²/Gün"),
                ("teknik", "Teknik Ekip (Teknisyen)", "Kişi/Gün"),
                # Transfer
                ("transfer", "VIP Araç (Sedan/Vito)", "Araç/Gün"),
                ("transfer", "Otobüs Transfer (Kapasite 50)", "Araç/Gün"),
                ("transfer", "Minibüs Transfer (Kapasite 20)", "Araç/Gün"),
                ("transfer", "Havalimanı Karşılama & Uğurlama", "Transfer"),
                ("transfer", "Şehir İçi Transfer", "Transfer"),
                # Diğer
                ("other", "Fotoğrafçı (Kurumsal)", "Gün"),
                ("other", "Video Çekimi & Kurgu", "Gün"),
                ("other", "Hostess (Karşılama)", "Kişi/Gün"),
                ("other", "Tercüman (İngilizce)", "Kişi/Gün"),
                ("other", "Çiçek Düzenlemesi", "Adet"),
                ("other", "Davetiye Tasarım & Baskı", "Adet"),
            ]
            services = [
                Service(id=_uuid(), category=cat, name=name, unit=unit, active=True)
                for cat, name, unit in services_data
            ]
            db.add_all(services)
            db.flush()
            print("  [seed] Hizmet kataloğu eklendi.")

        # ----------------------------------------------------------------
        # 5. Organizasyon Unvanları
        # ----------------------------------------------------------------
        if db.query(OrgTitle).count() == 0:
            id_gm   = _uuid(); id_gmy  = _uuid(); id_dir  = _uuid()
            id_egm  = _uuid(); id_esym = _uuid(); id_artd = _uuid(); id_fmbm = _uuid()
            id_ebm  = _uuid(); id_tsyk = _uuid(); id_dyk  = _uuid(); id_lok  = _uuid()
            id_gtym = _uuid(); id_fm   = _uuid(); id_mm   = _uuid()
            id_pym  = _uuid(); id_gtyk = _uuid(); id_fy   = _uuid(); id_my   = _uuid()
            id_ps   = _uuid(); id_pa   = _uuid()

            org_titles = [
                OrgTitle(id=id_gm,   name="Genel Müdür",                       grade=1, parent_id=None,    budget_limit=None, sort_order=1,  pm_permission_level="mudur"),
                OrgTitle(id=id_gmy,  name="Genel Müdür Yardımcısı",            grade=2, parent_id=id_gm,   budget_limit=None, sort_order=2,  pm_permission_level="mudur"),
                OrgTitle(id=id_dir,  name="Direktör",                          grade=3, parent_id=id_gmy,  budget_limit=None, sort_order=3,  pm_permission_level="mudur"),
                OrgTitle(id=id_egm,  name="Etkinlik Grup Müdürü",              grade=4, parent_id=id_dir,  budget_limit=None, sort_order=4,  pm_permission_level="mudur"),
                OrgTitle(id=id_esym, name="Etkinlik Süreç Yönetimi Müdürü",   grade=4, parent_id=id_dir,  budget_limit=None, sort_order=5,  pm_permission_level="mudur"),
                OrgTitle(id=id_artd, name="Art Direktör",                      grade=4, parent_id=id_dir,  budget_limit=None, sort_order=6,  pm_permission_level="mudur"),
                OrgTitle(id=id_fmbm, name="Finans ve Muhasebe Birimi Müdürü", grade=4, parent_id=id_dir,  budget_limit=None, sort_order=7,  pm_permission_level=None),
                OrgTitle(id=id_ebm,  name="Etkinlik Birim Müdürü",             grade=5, parent_id=id_egm,  budget_limit=None, sort_order=8,  pm_permission_level="mudur"),
                OrgTitle(id=id_tsyk, name="Teknik Servisler Yetkilisi",        grade=5, parent_id=id_esym, budget_limit=None, sort_order=9,  pm_permission_level=None),
                OrgTitle(id=id_dyk,  name="Dekor Yetkilisi",                   grade=5, parent_id=id_esym, budget_limit=None, sort_order=10, pm_permission_level=None),
                OrgTitle(id=id_lok,  name="Lojistik Yetkilisi",                grade=5, parent_id=id_esym, budget_limit=None, sort_order=11, pm_permission_level=None),
                OrgTitle(id=id_gtym, name="Grafik Tasarım Yöneticisi",         grade=5, parent_id=id_artd, budget_limit=None, sort_order=12, pm_permission_level=None),
                OrgTitle(id=id_fm,   name="Finans Müdürü",                     grade=5, parent_id=id_fmbm, budget_limit=None, sort_order=13, pm_permission_level=None),
                OrgTitle(id=id_mm,   name="Muhasebe Müdürü",                   grade=5, parent_id=id_fmbm, budget_limit=None, sort_order=14, pm_permission_level=None),
                OrgTitle(id=id_pym,  name="Proje Yöneticisi",                  grade=6, parent_id=id_ebm,  budget_limit=None, sort_order=15, pm_permission_level="yonetici"),
                OrgTitle(id=id_gtyk, name="Grafik Tasarım Yetkilisi",          grade=6, parent_id=id_gtym, budget_limit=None, sort_order=16, pm_permission_level=None),
                OrgTitle(id=id_fy,   name="Finans Yetkilisi",                  grade=6, parent_id=id_fm,   budget_limit=None, sort_order=17, pm_permission_level=None),
                OrgTitle(id=id_my,   name="Muhasebe Yetkilisi",                grade=6, parent_id=id_mm,   budget_limit=None, sort_order=18, pm_permission_level=None),
                OrgTitle(id=id_ps,   name="Proje Sorumlusu",                   grade=7, parent_id=id_pym,  budget_limit=None, sort_order=19, pm_permission_level="yonetici"),
                OrgTitle(id=id_pa,   name="Proje Asistanı",                    grade=8, parent_id=id_ps,   budget_limit=None, sort_order=20, pm_permission_level="asistan"),
            ]
            db.add_all(org_titles)
            db.flush()
            print("  [seed] Organizasyon unvanları eklendi.")

        # Sistem ayarları
        if db.query(Settings).count() == 0:
            db.add(Settings(
                id=1,
                company_name="miceapp",
                company_address="",
                company_phone="",
                company_email="",
                logo_url="",
                email_signature="",
                rfq_subject_tpl="{event_name} Fiyat Teklifi - {request_no}",
                currency="₺",
            ))
            db.flush()
            print("  [seed] Sistem ayarları eklendi.")

        # E-posta şablonları
        for tpl_data in _EMAIL_TEMPLATE_DEFAULTS:
            if not db.query(EmailTemplate).filter(EmailTemplate.slug == tpl_data["slug"]).first():
                db.add(EmailTemplate(
                    id=_uuid(),
                    slug=tpl_data["slug"],
                    name=tpl_data["name"],
                    description=tpl_data["description"],
                    subject_tpl=tpl_data["subject_tpl"],
                    body_tpl=tpl_data["body_tpl"],
                    active=True,
                    created_at=_now(),
                    updated_at=_now(),
                ))
        db.flush()
        print("  [seed] E-posta şablonları eklendi.")

        db.commit()
        print("  [seed] Tamamlandı.")

    except Exception as exc:
        db.rollback()
        print(f"  [seed] HATA: {exc}")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Yardımcı fonksiyon: referans no üretimi
# ---------------------------------------------------------------------------

def generate_ref_no(db, event_type_code: str, customer_code: str, check_in_str: str) -> str:
    """Talep referans numarası üretir: yi-abc-010426-a (miceapp suite: tireli format)"""
    import string as _string
    try:
        check_in = date.fromisoformat(check_in_str)
        ddmmyy = check_in.strftime("%d%m%y")
    except Exception:
        ddmmyy = date.today().strftime("%d%m%y")

    code   = (event_type_code or "yi").lower()
    mus    = (customer_code or "xxx").lower()[:3]
    prefix = f"{code}-{mus}-{ddmmyy}"

    # Find existing refs with same prefix to determine next letter
    existing = db.query(Request).filter(
        Request.request_no.like(f"{prefix}-%")
    ).all()

    used_letters = set()
    for r in existing:
        parts = r.request_no.split("-")
        if len(parts) == 4:
            used_letters.add(parts[3])

    for letter in _string.ascii_lowercase:
        if letter not in used_letters:
            return f"{prefix}-{letter}"

    return f"{prefix}-z"  # fallback


# ---------------------------------------------------------------------------
# Veritabanı migrasyon (mevcut tablolara yeni sütun ekler)
# ---------------------------------------------------------------------------

def _col_exists(conn, table: str, column: str) -> bool:
    """Sütunun tabloda var olup olmadığını kontrol eder (SQLite + PostgreSQL)."""
    if _is_sqlite:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == column for r in rows)
    else:
        row = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ), {"t": table, "c": column}).fetchone()
        return row is not None


def _safe_add_column(conn, table: str, column: str, col_type: str, default: str | None = None) -> None:
    """Sütun yoksa ekler, varsa sessizce geçer."""
    if _col_exists(conn, table, column):
        return
    default_sql = f" DEFAULT {default}" if default is not None else ""
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_sql}"))
    conn.commit()


def _seed_email_templates() -> None:
    """email_templates tablosuna eksik varsayılan şablonları ekler (idempotent)."""
    db = SessionLocal()
    try:
        for tpl_data in _EMAIL_TEMPLATE_DEFAULTS:
            if not db.query(EmailTemplate).filter(EmailTemplate.slug == tpl_data["slug"]).first():
                db.add(EmailTemplate(
                    id=_uuid(),
                    slug=tpl_data["slug"],
                    name=tpl_data["name"],
                    description=tpl_data["description"],
                    subject_tpl=tpl_data["subject_tpl"],
                    body_tpl=tpl_data["body_tpl"],
                    active=True,
                    created_at=_now(),
                    updated_at=_now(),
                ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def migrate_db():
    """Mevcut tablolara eksik sütunları ekler (SQLite + PostgreSQL uyumlu)."""
    with engine.connect() as conn:
        _safe_add_column(conn, "customers", "contacts_json",       "TEXT", "'{}'")
        _safe_add_column(conn, "requests",  "contact_person_json", "TEXT", "'{}'")
        _safe_add_column(conn, "users",     "org_title_id",        "TEXT")
        _safe_add_column(conn, "services",  "sort_order",          "INTEGER", "0")
        # miceapp suite: desk role_permissions'ı 'enabled' kolonuyla yaratmış olabilir;
        # event 'allowed' okuyor → ortak tabloda ikisi de bulunsun.
        _safe_add_column(conn, "role_permissions", "allowed", "BOOLEAN", "TRUE")
        # miceapp suite: HBF kredi kartı seçimi + limit düşüşü
        _safe_add_column(conn, "expense_items",    "credit_card_id",    "VARCHAR(36)")
        _safe_add_column(conn, "credit_card_txns", "expense_report_id", "VARCHAR(36)")
        # HBF tam onay zinciri (müdür→GM→muhasebe→kapandı) + tenant + ödeme kayıtları
        _safe_add_column(conn, "users",           "company_id",          "VARCHAR(36)")
        _safe_add_column(conn, "expense_reports", "company_id",          "VARCHAR(36)")
        _safe_add_column(conn, "expense_reports", "owner_approved_by",   "VARCHAR(36)")
        _safe_add_column(conn, "expense_reports", "owner_approved_at",   "TIMESTAMP")
        _safe_add_column(conn, "expense_reports", "manager_approved_by", "VARCHAR(36)")
        _safe_add_column(conn, "expense_reports", "manager_approved_at", "TIMESTAMP")
        _safe_add_column(conn, "expense_reports", "paid_by",             "VARCHAR(36)")
        _safe_add_column(conn, "expense_reports", "paid_at",             "TIMESTAMP")
        _safe_add_column(conn, "expense_reports", "payment_method",      "VARCHAR(20)")
        _safe_add_column(conn, "expense_reports", "bank_account_id",     "VARCHAR(36)")
        _safe_add_column(conn, "expense_reports", "cash_book_id",        "VARCHAR(36)")
        _safe_add_column(conn, "expense_reports", "general_expense_id",  "VARCHAR(36)")
        # Ön ödeme talebi: tenant + ödeme/ihtiyaç tarihi (desk muhasebe akışı için)
        _safe_add_column(conn, "prepayment_requests", "company_id",  "VARCHAR(36)")
        # ── Multi-tenant: Request, Invoice, Budget, VendorPrepayment ──────────
        _safe_add_column(conn, "requests",           "company_id", "VARCHAR(36)")
        _safe_add_column(conn, "invoices",           "company_id", "VARCHAR(36)")
        _safe_add_column(conn, "budgets",            "company_id", "VARCHAR(36)")
        _safe_add_column(conn, "vendor_prepayments", "company_id",  "VARCHAR(36)")
        _safe_add_column(conn, "vendor_prepayments", "request_id",  "VARCHAR(36)")
        _safe_add_column(conn, "vendor_prepayments", "updated_at",  "TIMESTAMP")
        # Event modeli applied_amount + status kullanıyor (fatura onayında _apply_prepayments);
        # tablo desk tarafından şekillendiği için bu kolonlar eksikti → fatura onayı 500 veriyordu.
        _safe_add_column(conn, "vendor_prepayments", "applied_amount", "DOUBLE PRECISION", "0")
        _safe_add_column(conn, "vendor_prepayments", "status",         "VARCHAR(16)", "'open'")
        # ── ut/yi tipi etkinlik: hekim + staff sayıları ────────────────────────
        _safe_add_column(conn, "requests", "hekim_count", "INTEGER")
        _safe_add_column(conn, "requests", "staff_count",  "INTEGER")
        # ── RFQ Şablon tablosu (create_all yeterli, ama eksik sütun koruması) ──
        _safe_add_column(conn, "request_templates", "description", "TEXT DEFAULT ''")
        _safe_add_column(conn, "request_templates", "company_id",  "VARCHAR(36)")
        _safe_add_column(conn, "prepayment_requests", "needed_date", "VARCHAR(10)")
        _safe_add_column(conn, "prepayment_requests", "document_path", "VARCHAR(500)")
        _safe_add_column(conn, "prepayment_requests", "document_name", "VARCHAR(255)")
        _safe_add_column(conn, "prepayment_requests", "approval_note", "VARCHAR(500)")
        # notifications.ref_id: eski şemada INTEGER → UUID string yazmak için VARCHAR'a çevir
        # (sadece hâlâ integer ise — idempotent, gereksiz tablo yeniden yazımı yapmaz)
        try:
            if not _is_sqlite:
                conn.execute(text(
                    "DO $$ BEGIN "
                    "IF EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='notifications' AND column_name='ref_id' "
                    "AND data_type='integer') THEN "
                    "ALTER TABLE notifications ALTER COLUMN ref_id TYPE VARCHAR(36) USING ref_id::varchar; "
                    "END IF; END $$"
                ))
                conn.commit()
        except Exception:
            conn.rollback()

        # role_permissions tablosu — yoksa oluştur
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS role_permissions (
                    id         TEXT PRIMARY KEY,
                    role       TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    allowed    INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(role, permission)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS role_permissions (
                    id         VARCHAR(36) PRIMARY KEY,
                    role       VARCHAR(32) NOT NULL,
                    permission VARCHAR(64) NOT NULL,
                    allowed    BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE(role, permission)
                )
            """))
        conn.commit()

        # Varsayılan izinleri seed et (yoksa ekle)
        from models import DEFAULT_ROLE_PERMISSIONS, PERMISSIONS, _uuid as _u
        all_keys = {p["key"] for p in PERMISSIONS}
        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
            for pkey in all_keys:
                allowed = pkey in perms
                try:
                    if _is_sqlite:
                        conn.execute(text(
                            "INSERT OR IGNORE INTO role_permissions (id, role, permission, allowed) VALUES (:id, :role, :perm, :allowed)"
                        ), {"id": _u(), "role": role, "perm": pkey, "allowed": 1 if allowed else 0})
                    else:
                        conn.execute(text(
                            "INSERT INTO role_permissions (id, role, permission, allowed) VALUES (:id, :role, :perm, :allowed) ON CONFLICT (role, permission) DO NOTHING"
                        ), {"id": _u(), "role": role, "perm": pkey, "allowed": allowed})
                except Exception:
                    pass
        conn.commit()
        _safe_add_column(conn, "users",     "avatar_b64",          "TEXT", "''")
        _safe_add_column(conn, "invoices",  "lines_json",          "TEXT", "'[]'")
        _safe_add_column(conn, "invoices",  "source_invoice_id",   "VARCHAR(36)")
        _safe_add_column(conn, "invoices",  "approval_status",     "VARCHAR(20)")
        _safe_add_column(conn, "invoices",  "approved_by",         "TEXT")
        _safe_add_column(conn, "invoices",  "approved_at",         "TEXT")
        _safe_add_column(conn, "invoices",  "rejection_note",      "TEXT", "''")
        # Mevcut "active" faturalar → "approved" (geriye uyumluluk — paylaşımlı DB'de enum olabilir, hata görmezden gel)
        try:
            conn.execute(text("UPDATE invoices SET status='approved' WHERE status='active'"))
            conn.commit()
        except Exception:
            conn.rollback()

        # Budgets
        _safe_add_column(conn, "budgets", "budget_status",       "TEXT",  "'draft_satinalma'")
        _safe_add_column(conn, "budgets", "revision_notes",      "TEXT",  "''")
        _safe_add_column(conn, "budgets", "manager_notes",       "TEXT",  "''")
        _safe_add_column(conn, "budgets", "service_fee_pct",     "REAL",  "0")
        _safe_add_column(conn, "budgets", "offer_currency",      "TEXT",  "'TRY'")
        _safe_add_column(conn, "budgets", "exchange_rates_json", "TEXT",  "'{}'")
        _safe_add_column(conn, "budgets", "venue_id",              "TEXT")
        _safe_add_column(conn, "budgets", "price_history_json",   "TEXT", "'[]'")
        _safe_add_column(conn, "budgets", "price_snapshots_json",  "TEXT", "'[]'")
        _safe_add_column(conn, "budgets", "budget_type",            "TEXT", "'offer'")
        _safe_add_column(conn, "budgets", "statement_status",       "TEXT")
        _safe_add_column(conn, "budgets", "statement_sent_at",      "TIMESTAMP")
        _safe_add_column(conn, "budgets", "statement_approved_at",  "TIMESTAMP")

        # HBF çok referans desteği
        _safe_add_column(conn, "expense_reports", "request_ids_json",    "TEXT", "''")
        _safe_add_column(conn, "expense_items",   "assigned_request_id", "TEXT")

        # Requests — post-offer workflow
        _safe_add_column(conn, "requests", "confirmed_at",        "TIMESTAMP")
        _safe_add_column(conn, "requests", "confirmed_budget_id", "TEXT")
        _safe_add_column(conn, "requests", "cancellation_reason", "TEXT",    "''")
        _safe_add_column(conn, "requests", "revision_count",      "INTEGER", "0")
        # Requests — fon / sponsor destekli etkinlik işaretleri
        _bool_type    = "INTEGER" if _is_sqlite else "BOOLEAN"
        _bool_default = "0" if _is_sqlite else "FALSE"
        _safe_add_column(conn, "requests", "is_funded",      _bool_type, _bool_default)
        _safe_add_column(conn, "requests", "funding_source", "TEXT",     "''")
        # Requests — Fon havuzu kolonları
        _safe_add_column(conn, "requests", "is_fund_pool",           _bool_type, _bool_default)
        _safe_add_column(conn, "requests", "parent_fund_request_id", "TEXT")
        _safe_add_column(conn, "requests", "fund_currency",          "TEXT",  "'TRY'")
        _safe_add_column(conn, "requests", "fund_initial_amount",    "REAL",  "0.0")
        _safe_add_column(conn, "requests", "fund_initial_vat_rate",  "REAL",  "20.0")
        _safe_add_column(conn, "requests", "fund_pool_type",         "TEXT",  "'customer'")
        _safe_add_column(conn, "requests", "fund_vendor_name",       "TEXT",  "''")
        # Invoices — bölme alanları
        _safe_add_column(conn, "invoices", "is_split_parent",        _bool_type, _bool_default)
        _safe_add_column(conn, "invoices", "parent_invoice_id",      "TEXT")

        # Invoices — micedesk köprü alanları (koordinatör onay akışı, Faz 1)
        _safe_add_column(conn, "invoices", "ref_id",                  "TEXT")
        _safe_add_column(conn, "invoices", "coordinator_status",      "TEXT")
        _safe_add_column(conn, "invoices", "coordinator_note",        "TEXT")
        _safe_add_column(conn, "invoices", "coordinator_reviewed_at", "TIMESTAMP")
        _safe_add_column(conn, "invoices", "coordinator_reviewed_by", "TEXT")
        _safe_add_column(conn, "invoices", "notes",                    "TEXT")

        # fund_transfers tablosu
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS fund_transfers (
                    id                  TEXT PRIMARY KEY,
                    fund_request_id     TEXT NOT NULL REFERENCES requests(id),
                    related_request_id  TEXT NOT NULL REFERENCES requests(id),
                    direction           TEXT NOT NULL,
                    amount              REAL NOT NULL,
                    vat_rate            REAL DEFAULT 20.0,
                    currency            TEXT DEFAULT 'TRY',
                    exchange_rate_try   REAL DEFAULT 1.0,
                    description         TEXT DEFAULT '',
                    transfer_date       TEXT NOT NULL,
                    created_by          TEXT NOT NULL REFERENCES users(id),
                    created_at          TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_fund_transfers_fund ON fund_transfers(fund_request_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_fund_transfers_related ON fund_transfers(related_request_id)"
            ))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS fund_transfers (
                    id                  VARCHAR(36) PRIMARY KEY,
                    fund_request_id     VARCHAR(36) NOT NULL REFERENCES requests(id),
                    related_request_id  VARCHAR(36) NOT NULL REFERENCES requests(id),
                    direction           VARCHAR(10) NOT NULL,
                    amount              DOUBLE PRECISION NOT NULL,
                    vat_rate            DOUBLE PRECISION DEFAULT 20.0,
                    currency            VARCHAR(3) DEFAULT 'TRY',
                    exchange_rate_try   DOUBLE PRECISION DEFAULT 1.0,
                    description         TEXT DEFAULT '',
                    transfer_date       VARCHAR(10) NOT NULL,
                    created_by          VARCHAR(36) NOT NULL REFERENCES users(id),
                    created_at          TIMESTAMP
                )
            """))
            # INDEX'ler ayrı transaction'da — paylaşımlı DB'de kolon olmayabilir
            for _idx_sql in [
                "CREATE INDEX IF NOT EXISTS ix_fund_transfers_fund ON fund_transfers(fund_request_id)",
                "CREATE INDEX IF NOT EXISTS ix_fund_transfers_related ON fund_transfers(related_request_id)",
            ]:
                try:
                    with engine.begin() as _ic:
                        _ic.execute(text(_idx_sql))
                except Exception as _e:
                    print(f"[migrate] fund_transfers index atlandı: {_e}")
        conn.commit()

        # Customers
        _safe_add_column(conn, "customers", "excel_template_path", "TEXT", "''")
        _safe_add_column(conn, "customers", "excel_template_b64",  "TEXT", "''")
        _safe_add_column(conn, "customers", "excel_config_json",   "TEXT", "'{}'")
        _safe_add_column(conn, "customers", "docs_json",           "TEXT", "'[]'")

        # RequestModule — yeni portal URL kolonları
        _safe_add_column(conn, "request_modules", "oa_task_supplier_url", "TEXT")
        _safe_add_column(conn, "request_modules", "oa_client_url",        "TEXT")

        # Invoices tablosu — yoksa oluştur
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id            TEXT PRIMARY KEY,
                    request_id    TEXT NOT NULL REFERENCES requests(id),
                    invoice_type  TEXT NOT NULL,
                    invoice_no    TEXT DEFAULT '',
                    invoice_date  TEXT,
                    due_date      TEXT,
                    vendor_name   TEXT DEFAULT '',
                    description   TEXT DEFAULT '',
                    amount        REAL DEFAULT 0.0,
                    vat_rate      REAL DEFAULT 20.0,
                    vat_amount    REAL DEFAULT 0.0,
                    total_amount  REAL DEFAULT 0.0,
                    document_path TEXT,
                    document_name TEXT,
                    status        TEXT DEFAULT 'active',
                    created_by    TEXT NOT NULL REFERENCES users(id),
                    created_at    TIMESTAMP,
                    updated_at    TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_request_id ON invoices(request_id)"))
            except Exception as _e:
                print(f"[migrate] ix_invoices_request_id atlandı: {_e}")
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id            VARCHAR(36) PRIMARY KEY,
                    request_id    VARCHAR(36) NOT NULL REFERENCES requests(id),
                    invoice_type  VARCHAR(32) NOT NULL,
                    invoice_no    VARCHAR(100) DEFAULT '',
                    invoice_date  VARCHAR(10),
                    due_date      VARCHAR(10),
                    vendor_name   VARCHAR(255) DEFAULT '',
                    description   TEXT DEFAULT '',
                    amount        FLOAT DEFAULT 0.0,
                    vat_rate      FLOAT DEFAULT 20.0,
                    vat_amount    FLOAT DEFAULT 0.0,
                    total_amount  FLOAT DEFAULT 0.0,
                    document_path VARCHAR(500),
                    document_name VARCHAR(255),
                    status        VARCHAR(16) DEFAULT 'active',
                    created_by    VARCHAR(36) NOT NULL REFERENCES users(id),
                    created_at    TIMESTAMP,
                    updated_at    TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_request_id ON invoices(request_id)"))
            except Exception as _e:
                print(f"[migrate] ix_invoices_request_id atlandı: {_e}")
        # email_templates tablosu — yoksa oluştur
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS email_templates (
                    id          TEXT PRIMARY KEY,
                    slug        TEXT UNIQUE NOT NULL,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    subject_tpl TEXT NOT NULL,
                    body_tpl    TEXT NOT NULL,
                    active      INTEGER DEFAULT 1,
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS email_templates (
                    id          VARCHAR(36) PRIMARY KEY,
                    slug        VARCHAR(64) UNIQUE NOT NULL,
                    name        VARCHAR(200) NOT NULL,
                    description VARCHAR(400) DEFAULT '',
                    subject_tpl VARCHAR(400) NOT NULL,
                    body_tpl    TEXT NOT NULL,
                    active      BOOLEAN DEFAULT TRUE,
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP
                )
            """))
        conn.commit()

        # HBF — expense_reports tablosu
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS expense_reports (
                    id             TEXT PRIMARY KEY,
                    request_id     TEXT NOT NULL REFERENCES requests(id),
                    title          TEXT DEFAULT '',
                    status         TEXT DEFAULT 'draft',
                    submitted_by   TEXT NOT NULL REFERENCES users(id),
                    approved_by    TEXT,
                    approved_at    TIMESTAMP,
                    rejection_note TEXT DEFAULT '',
                    created_at     TIMESTAMP,
                    updated_at     TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_expense_reports_request_id ON expense_reports(request_id)"))
            except Exception as _e:
                print(f"[migrate] ix_expense_reports_request_id atlandı: {_e}")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS expense_items (
                    id             TEXT PRIMARY KEY,
                    report_id      TEXT NOT NULL REFERENCES expense_reports(id),
                    item_date      TEXT DEFAULT '',
                    description    TEXT DEFAULT '',
                    payment_method TEXT DEFAULT 'nakit',
                    document_type  TEXT DEFAULT 'fis',
                    amount         REAL DEFAULT 0.0,
                    vat_rate       REAL DEFAULT 0.0,
                    vat_amount     REAL DEFAULT 0.0,
                    total_amount   REAL DEFAULT 0.0,
                    document_path  TEXT,
                    document_name  TEXT,
                    sort_order     INTEGER DEFAULT 0,
                    created_at     TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_expense_items_report_id ON expense_items(report_id)"))
            except Exception as _e:
                print(f"[migrate] ix_expense_items_report_id atlandı: {_e}")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS undocumented_entries (
                    id          TEXT PRIMARY KEY,
                    request_id  TEXT NOT NULL REFERENCES requests(id),
                    entry_type  TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    amount      REAL DEFAULT 0.0,
                    entry_date  TEXT DEFAULT '',
                    created_by  TEXT NOT NULL REFERENCES users(id),
                    created_at  TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_undocumented_entries_request_id ON undocumented_entries(request_id)"))
            except Exception as _e:
                print(f"[migrate] ix_undocumented_entries_request_id atlandı: {_e}")
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS expense_reports (
                    id             VARCHAR(36) PRIMARY KEY,
                    request_id     VARCHAR(36) NOT NULL REFERENCES requests(id),
                    title          VARCHAR(300) DEFAULT '',
                    status         VARCHAR(16) DEFAULT 'draft',
                    submitted_by   VARCHAR(36) NOT NULL REFERENCES users(id),
                    approved_by    VARCHAR(36),
                    approved_at    TIMESTAMP,
                    rejection_note TEXT DEFAULT '',
                    created_at     TIMESTAMP,
                    updated_at     TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_expense_reports_request_id ON expense_reports(request_id)"))
            except Exception as _e:
                print(f"[migrate] ix_expense_reports_request_id atlandı: {_e}")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS expense_items (
                    id             VARCHAR(36) PRIMARY KEY,
                    report_id      VARCHAR(36) NOT NULL REFERENCES expense_reports(id),
                    item_date      VARCHAR(10) DEFAULT '',
                    description    VARCHAR(300) DEFAULT '',
                    payment_method VARCHAR(16) DEFAULT 'nakit',
                    document_type  VARCHAR(16) DEFAULT 'fis',
                    amount         FLOAT DEFAULT 0.0,
                    vat_rate       FLOAT DEFAULT 0.0,
                    vat_amount     FLOAT DEFAULT 0.0,
                    total_amount   FLOAT DEFAULT 0.0,
                    document_path  VARCHAR(500),
                    document_name  VARCHAR(255),
                    sort_order     INTEGER DEFAULT 0,
                    created_at     TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_expense_items_report_id ON expense_items(report_id)"))
            except Exception as _e:
                print(f"[migrate] ix_expense_items_report_id atlandı: {_e}")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS undocumented_entries (
                    id          VARCHAR(36) PRIMARY KEY,
                    request_id  VARCHAR(36) NOT NULL REFERENCES requests(id),
                    entry_type  VARCHAR(8) NOT NULL,
                    description VARCHAR(300) DEFAULT '',
                    amount      FLOAT DEFAULT 0.0,
                    entry_date  VARCHAR(10) DEFAULT '',
                    created_by  VARCHAR(36) NOT NULL REFERENCES users(id),
                    created_at  TIMESTAMP
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_undocumented_entries_request_id ON undocumented_entries(request_id)"))
            except Exception as _e:
                print(f"[migrate] ix_undocumented_entries_request_id atlandı: {_e}")
        conn.commit()

        # notifications tablosu
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id         TEXT PRIMARY KEY,
                    user_id    TEXT NOT NULL REFERENCES users(id),
                    notif_type TEXT NOT NULL,
                    title      TEXT NOT NULL,
                    message    TEXT DEFAULT '',
                    link       TEXT DEFAULT '',
                    ref_id     TEXT DEFAULT '',
                    read_at    TEXT,
                    created_at TEXT NOT NULL
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id)"))
            except Exception as _e:
                print(f"[migrate] ix_notifications_user_id atlandı: {_e}")
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id         VARCHAR(36) PRIMARY KEY,
                    user_id    VARCHAR(36) NOT NULL REFERENCES users(id),
                    notif_type VARCHAR(50) NOT NULL,
                    title      VARCHAR(200) NOT NULL,
                    message    VARCHAR(500) DEFAULT '',
                    link       VARCHAR(500) DEFAULT '',
                    ref_id     VARCHAR(36)  DEFAULT '',
                    read_at    TIMESTAMP,
                    created_at TIMESTAMP NOT NULL
                )
            """))
            try:
                with engine.begin() as _ic:
                    _ic.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id)"))
            except Exception as _e:
                print(f"[migrate] ix_notifications_user_id atlandı: {_e}")
        conn.commit()

        # closure_requests tablosu
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS closure_requests (
                    id              TEXT PRIMARY KEY,
                    request_id      TEXT NOT NULL UNIQUE REFERENCES requests(id),
                    submitted_by    TEXT NOT NULL REFERENCES users(id),
                    submitted_at    TIMESTAMP,
                    note            TEXT DEFAULT '',
                    l1_approver_id  TEXT REFERENCES users(id),
                    l1_approved_at  TIMESTAMP,
                    l1_note         TEXT DEFAULT '',
                    l2_approver_id  TEXT REFERENCES users(id),
                    l2_approved_at  TIMESTAMP,
                    l2_note         TEXT DEFAULT '',
                    rejection_note  TEXT DEFAULT '',
                    rejected_by_id  TEXT REFERENCES users(id),
                    rejected_at     TIMESTAMP,
                    status          TEXT DEFAULT 'pending_manager',
                    created_at      TIMESTAMP,
                    updated_at      TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_closure_requests_request_id ON closure_requests(request_id)"
            ))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS closure_requests (
                    id              VARCHAR(36) PRIMARY KEY,
                    request_id      VARCHAR(36) NOT NULL UNIQUE REFERENCES requests(id),
                    submitted_by    VARCHAR(36) NOT NULL REFERENCES users(id),
                    submitted_at    TIMESTAMP,
                    note            TEXT DEFAULT '',
                    l1_approver_id  VARCHAR(36) REFERENCES users(id),
                    l1_approved_at  TIMESTAMP,
                    l1_note         TEXT DEFAULT '',
                    l2_approver_id  VARCHAR(36) REFERENCES users(id),
                    l2_approved_at  TIMESTAMP,
                    l2_note         TEXT DEFAULT '',
                    rejection_note  TEXT DEFAULT '',
                    rejected_by_id  VARCHAR(36) REFERENCES users(id),
                    rejected_at     TIMESTAMP,
                    status          VARCHAR(24) DEFAULT 'pending_manager',
                    created_at      TIMESTAMP,
                    updated_at      TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_closure_requests_request_id ON closure_requests(request_id)"
            ))
        conn.commit()

        # OrgTitle — pm_permission_level sütunu
        _safe_add_column(conn, "org_titles", "pm_permission_level", "TEXT")

        # Dosya kapama — Genel Müdür onay adımı
        _safe_add_column(conn, "closure_requests", "needs_gm",       "BOOLEAN", "FALSE")
        _safe_add_column(conn, "closure_requests", "gm_approver_id", "TEXT")
        _safe_add_column(conn, "closure_requests", "gm_approved_at", "TIMESTAMP")
        _safe_add_column(conn, "closure_requests", "gm_note",        "TEXT", "''")
        # OrgTitle grade'e göre varsayılan pm_permission_level ata (zaten atanmamışsa)
        conn.execute(text(
            "UPDATE org_titles SET pm_permission_level='mudur' "
            "WHERE pm_permission_level IS NULL AND grade <= 2"
        ))
        conn.execute(text(
            "UPDATE org_titles SET pm_permission_level='yonetici' "
            "WHERE pm_permission_level IS NULL AND grade BETWEEN 3 AND 5"
        ))
        conn.execute(text(
            "UPDATE org_titles SET pm_permission_level='asistan' "
            "WHERE pm_permission_level IS NULL AND grade >= 6"
        ))
        conn.commit()

        # project_manager rolünü yonetici'ye rename et (geriye uyumluluk)
        conn.execute(text(
            "UPDATE users SET role='yonetici' WHERE role='project_manager'"
        ))
        conn.commit()

        # ── Takım tablosu ve yeni kullanıcı kolonları ──
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS teams (
                    id          TEXT    PRIMARY KEY,
                    name        VARCHAR(200) NOT NULL,
                    code        VARCHAR(50)  DEFAULT '',
                    description TEXT         DEFAULT '',
                    active      BOOLEAN      DEFAULT 1,
                    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()
        _safe_add_column(conn, "teams", "code", "TEXT", "''")
        _safe_add_column(conn, "users", "team_id",    "TEXT")
        _safe_add_column(conn, "users", "manager_id", "TEXT")
        _safe_add_column(conn, "settings", "invoice_mudur_limit", "REAL")

        # Takım tabanlı erişim: customers ve requests tablolarına team_id ekle
        _safe_add_column(conn, "customers", "team_id", "TEXT")
        _safe_add_column(conn, "requests",  "team_id", "TEXT")
        # Destek ekibi bayrağı
        _safe_add_column(conn, "teams", "is_support_team", "BOOLEAN DEFAULT FALSE")
        # Backfill: mevcut requests için created_by → user.team_id
        if not _is_sqlite:
            try:
                conn.execute(text(
                    "UPDATE requests SET team_id = ("
                    "  SELECT u.team_id FROM users u WHERE u.id = requests.created_by"
                    ") WHERE team_id IS NULL"
                ))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"[DB] requests.team_id backfill hatası: {e}", flush=True)
        else:
            try:
                conn.execute(text(
                    "UPDATE requests SET team_id = ("
                    "  SELECT u.team_id FROM users u WHERE u.id = requests.created_by"
                    ") WHERE team_id IS NULL"
                ))
                conn.commit()
            except Exception as e:
                conn.rollback()

        # invoices tablosu micedesk tarafından oluşturulmuş olabilir (paylaşımlı DB).
        # request_id kolonu micedesk'te yok — yoksa ekle.
        _safe_add_column(conn, "invoices", "request_id", "VARCHAR(36)")

        # invoices.request_id → nullable (referanssız fatura desteği)
        # information_schema'dan kontrol edip sadece gerektiğinde ALTER çalıştır
        if not _is_sqlite:
            try:
                row = conn.execute(text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name='invoices' AND column_name='request_id'"
                )).fetchone()
                if row and row[0] == 'NO':
                    conn.execute(text(
                        "ALTER TABLE invoices ALTER COLUMN request_id DROP NOT NULL"
                    ))
                    conn.commit()
                    print("[DB] invoices.request_id NOT NULL kısıtı kaldırıldı.", flush=True)
            except Exception as e:
                conn.rollback()
                print(f"[DB] invoices.request_id migration hatası: {e}", flush=True)

        # ── Vendor tablosu (birleşik: eski Venue + FinancialVendor) — yoksa oluştur ──
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id              TEXT PRIMARY KEY,
                    company_id      TEXT,
                    name            TEXT NOT NULL,
                    active          INTEGER DEFAULT 1,
                    supplier_type   TEXT DEFAULT 'diger',
                    city            TEXT DEFAULT '',
                    cities_json     TEXT DEFAULT '[]',
                    location_type   TEXT DEFAULT 'turkiye',
                    address         TEXT DEFAULT '',
                    phone           TEXT DEFAULT '',
                    email           TEXT DEFAULT '',
                    contact         TEXT DEFAULT '',
                    contacts_json   TEXT DEFAULT '[]',
                    website         TEXT DEFAULT '',
                    stars           INTEGER,
                    total_rooms     INTEGER DEFAULT 0,
                    halls_json      TEXT DEFAULT '[]',
                    docs_json       TEXT DEFAULT '[]',
                    tax_no          TEXT DEFAULT '',
                    tax_office      TEXT DEFAULT '',
                    iban            TEXT DEFAULT '',
                    bank_accounts_json TEXT,
                    payment_term    INTEGER DEFAULT 30,
                    is_efatura_user INTEGER,
                    efatura_alias   TEXT,
                    efatura_checked_at TIMESTAMP,
                    notes           TEXT DEFAULT '',
                    created_by      TEXT REFERENCES users(id),
                    created_at      TIMESTAMP,
                    updated_at      TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_vendors_name ON vendors(name)"
            ))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id              VARCHAR(36) PRIMARY KEY,
                    company_id      VARCHAR(36),
                    name            VARCHAR(255) NOT NULL,
                    active          BOOLEAN DEFAULT TRUE,
                    supplier_type   VARCHAR(50) DEFAULT 'diger',
                    city            VARCHAR(100) DEFAULT '',
                    cities_json     TEXT DEFAULT '[]',
                    location_type   VARCHAR(20) DEFAULT 'turkiye',
                    address         TEXT DEFAULT '',
                    phone           VARCHAR(50) DEFAULT '',
                    email           VARCHAR(255) DEFAULT '',
                    contact         VARCHAR(200) DEFAULT '',
                    contacts_json   TEXT DEFAULT '[]',
                    website         VARCHAR(255) DEFAULT '',
                    stars           INTEGER,
                    total_rooms     INTEGER DEFAULT 0,
                    halls_json      TEXT DEFAULT '[]',
                    docs_json       TEXT DEFAULT '[]',
                    tax_no          VARCHAR(30) DEFAULT '',
                    tax_office      VARCHAR(100) DEFAULT '',
                    iban            VARCHAR(40) DEFAULT '',
                    bank_accounts_json TEXT,
                    payment_term    INTEGER DEFAULT 30,
                    is_efatura_user BOOLEAN,
                    efatura_alias   VARCHAR(100),
                    efatura_checked_at TIMESTAMP,
                    notes           TEXT DEFAULT '',
                    created_by      VARCHAR(36) REFERENCES users(id),
                    created_at      TIMESTAMP,
                    updated_at      TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_vendors_name ON vendors(name)"
            ))
        conn.commit()

        # ── Eski financial_vendors tablosunu koru (geriye uyumluluk, varsa) ──
        # Yeni kayıtlar vendors tablosuna gider; eski veriler migrate edilene kadar burada kalır
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS financial_vendors (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    tax_number   TEXT DEFAULT '',
                    tax_office   TEXT DEFAULT '',
                    address      TEXT DEFAULT '',
                    email        TEXT DEFAULT '',
                    phone        TEXT DEFAULT '',
                    payment_term INTEGER DEFAULT 30,
                    notes        TEXT DEFAULT '',
                    is_active    INTEGER DEFAULT 1,
                    created_by   TEXT REFERENCES users(id),
                    created_at   TIMESTAMP,
                    updated_at   TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS financial_vendors (
                    id           VARCHAR(36) PRIMARY KEY,
                    name         VARCHAR(255) NOT NULL,
                    tax_number   VARCHAR(30) DEFAULT '',
                    tax_office   VARCHAR(100) DEFAULT '',
                    address      TEXT DEFAULT '',
                    email        VARCHAR(255) DEFAULT '',
                    phone        VARCHAR(30) DEFAULT '',
                    payment_term INTEGER DEFAULT 30,
                    notes        TEXT DEFAULT '',
                    is_active    BOOLEAN DEFAULT TRUE,
                    created_by   VARCHAR(36) REFERENCES users(id),
                    created_at   TIMESTAMP,
                    updated_at   TIMESTAMP
                )
            """))
        conn.commit()

        # ── Invoice — yeni sütunlar (vendor_id, payment_status, paid_at) ──
        _safe_add_column(conn, "invoices", "vendor_id",           "TEXT")
        _safe_add_column(conn, "invoices", "payment_status",      "TEXT", "'unpaid'")
        _safe_add_column(conn, "invoices", "paid_at",             "TEXT")
        _safe_add_column(conn, "invoices", "current_approver_id", "TEXT")
        _safe_add_column(conn, "invoices", "paid_amount",          "REAL",  "0")
        _safe_add_column(conn, "invoices", "payment_method",      "TEXT",  "'banka'")
        _safe_add_column(conn, "invoices", "cc_due_date",         "TEXT")
        _safe_add_column(conn, "invoices", "cc_pending_amount",   "REAL",  "0")

        # ── vendor_prepayments tablosu ───────────────────────────────────────
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS vendor_prepayments (
                    id             TEXT PRIMARY KEY,
                    vendor_id      TEXT NOT NULL REFERENCES vendors(id),
                    request_id     TEXT REFERENCES requests(id),
                    amount         REAL DEFAULT 0,
                    applied_amount REAL DEFAULT 0,
                    payment_date   TEXT NOT NULL,
                    payment_method TEXT DEFAULT 'banka',
                    notes          TEXT DEFAULT '',
                    status         TEXT DEFAULT 'open',
                    created_by     TEXT NOT NULL REFERENCES users(id),
                    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS vendor_prepayments (
                    id             VARCHAR(36) PRIMARY KEY,
                    vendor_id      VARCHAR(36) NOT NULL REFERENCES vendors(id),
                    request_id     VARCHAR(36) REFERENCES requests(id),
                    amount         FLOAT DEFAULT 0,
                    applied_amount FLOAT DEFAULT 0,
                    payment_date   VARCHAR(10) NOT NULL,
                    payment_method VARCHAR(20) DEFAULT 'banka',
                    notes          TEXT DEFAULT '',
                    status         VARCHAR(16) DEFAULT 'open',
                    created_by     VARCHAR(36) NOT NULL REFERENCES users(id),
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at     TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
        conn.commit()

        # ── invoice_logs tablosu ──────────────────────────────────────────────
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invoice_logs (
                    id             TEXT PRIMARY KEY,
                    invoice_id     TEXT NOT NULL REFERENCES invoices(id),
                    action         TEXT NOT NULL,
                    actor_id       TEXT REFERENCES users(id),
                    amount         REAL,
                    payment_method TEXT,
                    cc_due_date    TEXT,
                    note           TEXT DEFAULT '',
                    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invoice_logs (
                    id             VARCHAR(36) PRIMARY KEY,
                    invoice_id     VARCHAR(36) NOT NULL REFERENCES invoices(id),
                    action         VARCHAR(32) NOT NULL,
                    actor_id       VARCHAR(36) REFERENCES users(id),
                    amount         FLOAT,
                    payment_method VARCHAR(20),
                    cc_due_date    VARCHAR(10),
                    note           TEXT DEFAULT '',
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
        conn.commit()

        # ── prepayment_requests tablosu ───────────────────────────────────────
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS prepayment_requests (
                    id                   TEXT PRIMARY KEY,
                    vendor_id            TEXT NOT NULL REFERENCES vendors(id),
                    request_id           TEXT REFERENCES requests(id),
                    amount               REAL NOT NULL,
                    description          TEXT DEFAULT '',
                    notes                TEXT DEFAULT '',
                    status               TEXT NOT NULL DEFAULT 'pending_gm',
                    requested_by         TEXT NOT NULL REFERENCES users(id),
                    requested_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    approved_by          TEXT REFERENCES users(id),
                    approved_at          DATETIME,
                    rejection_note       TEXT DEFAULT '',
                    paid_by              TEXT REFERENCES users(id),
                    paid_at              TEXT,
                    payment_method       TEXT,
                    cc_due_date          TEXT,
                    vendor_prepayment_id TEXT REFERENCES vendor_prepayments(id),
                    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS prepayment_request_logs (
                    id                    TEXT PRIMARY KEY,
                    prepayment_request_id TEXT NOT NULL REFERENCES prepayment_requests(id),
                    action                TEXT NOT NULL,
                    actor_id              TEXT REFERENCES users(id),
                    note                  TEXT DEFAULT '',
                    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS prepayment_requests (
                    id                   VARCHAR(36) PRIMARY KEY,
                    vendor_id            VARCHAR(36) NOT NULL REFERENCES vendors(id),
                    request_id           VARCHAR(36) REFERENCES requests(id),
                    amount               FLOAT NOT NULL,
                    description          TEXT DEFAULT '',
                    notes                TEXT DEFAULT '',
                    status               VARCHAR(20) NOT NULL DEFAULT 'pending_gm',
                    requested_by         VARCHAR(36) NOT NULL REFERENCES users(id),
                    requested_at         TIMESTAMP NOT NULL DEFAULT NOW(),
                    approved_by          VARCHAR(36) REFERENCES users(id),
                    approved_at          TIMESTAMP,
                    rejection_note       VARCHAR(500) DEFAULT '',
                    paid_by              VARCHAR(36) REFERENCES users(id),
                    paid_at              VARCHAR(10),
                    payment_method       VARCHAR(20),
                    cc_due_date          VARCHAR(10),
                    vendor_prepayment_id VARCHAR(36) REFERENCES vendor_prepayments(id),
                    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS prepayment_request_logs (
                    id                    VARCHAR(36) PRIMARY KEY,
                    prepayment_request_id VARCHAR(36) NOT NULL REFERENCES prepayment_requests(id),
                    action                VARCHAR(32) NOT NULL,
                    actor_id              VARCHAR(36) REFERENCES users(id),
                    note                  TEXT DEFAULT '',
                    created_at            TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
        conn.commit()

        # Mevcut bekleyen faturaları backfill: request sahibini current_approver_id yap
        try:
            with engine.begin() as _ic:
                _ic.execute(text(
                    "UPDATE invoices SET current_approver_id = ("
                    "  SELECT created_by FROM requests WHERE requests.id = invoices.request_id"
                    ") WHERE status = 'pending' AND request_id IS NOT NULL AND current_approver_id IS NULL"
                ))
        except Exception as _e:
            print(f"[migrate] invoices backfill atlandı: {_e}")

        # Eksik seed şablonlarını ekle (idempotent)
        _seed_email_templates()

    # Müşterilere kontak kişi ekle — kontak yoksa HER ZAMAN güncelle
    SEED_CONTACTS = {
        "abc": [
            {"name": "Ayşe Kara",    "title": "Etkinlik Koordinatörü",  "email": "a.kara@abcteknoloji.com",  "phone": "+90 532 111 2233"},
            {"name": "Mert Doğan",   "title": "Genel Müdür Yardımcısı", "email": "m.dogan@abcteknoloji.com", "phone": "+90 532 111 4455"},
        ],
        "xyz": [
            {"name": "Selin Yıldız", "title": "Kurumsal İletişim Müdürü", "email": "s.yildiz@xyzholding.com", "phone": "+90 541 222 3344"},
            {"name": "Burak Çelik",  "title": "İdari İşler Uzmanı",       "email": "b.celik@xyzholding.com",  "phone": "+90 541 222 5566"},
        ],
        "def": [
            {"name": "Hande Arslan", "title": "Proje Müdürü", "email": "h.arslan@definsaat.com",  "phone": "+90 553 333 7788"},
            {"name": "Tolga Yılmaz", "title": "Genel Müdür",  "email": "t.yilmaz@definsaat.com",  "phone": "+90 553 333 9900"},
        ],
    }
    db_c = SessionLocal()
    try:
        for cust_code, contacts in SEED_CONTACTS.items():
            c = db_c.query(Customer).filter(Customer.code == cust_code).first()
            if not c:
                continue
            # Mevcut kontak sayısını kontrol et — boşsa güncelle
            try:
                existing = json.loads(c.contacts_json or "[]")
            except Exception:
                existing = []
            if not existing:
                c.contacts_json = json.dumps(contacts, ensure_ascii=False)
                print(f"  [migrate] {cust_code} kontakları eklendi.")
        db_c.commit()
    except Exception as e:
        db_c.rollback()
        print(f"  [migrate] Kontak ekleme hatası: {e}")
    finally:
        db_c.close()

    # Sonradan eklenen org unvanları
    db = SessionLocal()
    try:
        fmbm = db.query(OrgTitle).filter(OrgTitle.name == "Finans ve Muhasebe Birimi Müdürü").first()
        if fmbm and not db.query(OrgTitle).filter(OrgTitle.name == "Satın Alma Müdürü").first():
            sam = OrgTitle(id=_uuid(), name="Satın Alma Müdürü", grade=5,
                           parent_id=fmbm.id, budget_limit=None, sort_order=14)
            db.add(sam)
            db.flush()
            db.add(OrgTitle(id=_uuid(), name="Satın Alma Yetkilisi", grade=6,
                            parent_id=sam.id, budget_limit=None, sort_order=18))
            db.commit()
            print("  [migrate] Satın Alma unvanları eklendi.")
    except Exception as e:
        db.rollback()
        print(f"  [migrate] Satın Alma unvanları eklenemedi: {e}")
    finally:
        db.close()

    # is_gm unification (2026-06): org_title.grade=1 olan kullanıcıları genel_mudur yap
    # Raw SQL — ORM join kullanmıyoruz, PostgreSQL/SQLite uyumlu.
    with engine.connect() as _conn:
        try:
            _result = _conn.execute(text(
                "UPDATE users SET role='genel_mudur' "
                "WHERE role NOT IN ('admin','super_admin','genel_mudur') "
                "AND org_title_id IS NOT NULL "
                "AND org_title_id IN (SELECT id FROM org_titles WHERE grade = 1)"
            ))
            if _result.rowcount > 0:
                print(f"  [migrate] {_result.rowcount} kullanıcı genel_mudur rolüne yükseltildi.", flush=True)
            _conn.commit()
        except Exception as _e:
            _conn.rollback()
            print(f"  [migrate] GM rol yükseltme atlandı: {_e}", flush=True)


def _seed_event_company() -> None:
    """Event app için varsayılan şirket kaydı oluşturur ve mevcut verileri atar.
    Idempotent: companies tablosunda 'event' slug'ı varsa tekrar yazmaz."""
    from sqlalchemy import text as _text
    EVENT_COMPANY_ID = "78c37983-7c75-4489-a1ec-c6c1d33f0daf"  # kanonik: STOK Mice
    with engine.begin() as conn:
        # companies tablosu yoksa oluşturma — desk zaten oluşturmuştur
        try:
            # Şirket var mı?
            row = conn.execute(_text(
                "SELECT id FROM companies WHERE id = :cid"
            ), {"cid": EVENT_COMPANY_ID}).fetchone()
            if not row:
                conn.execute(_text("""
                    INSERT INTO companies (id, name, short_name, email, active, created_at)
                    VALUES (:id, :name, :sname, :email, TRUE, NOW())
                    ON CONFLICT (id) DO NOTHING
                """), {
                    "id": EVENT_COMPANY_ID,
                    "name": "miceapp Event",
                    "sname": "event",
                    "email": "event@miceapp.net",
                })
                print(f"  [seed] Event şirketi oluşturuldu (id={EVENT_COMPANY_ID})")
            # Mevcut verileri event şirketine ata (company_id NULL olanları)
            for tbl in ("requests", "invoices", "budgets", "vendor_prepayments"):
                result = conn.execute(_text(
                    f"UPDATE {tbl} SET company_id = :cid WHERE company_id IS NULL"
                ), {"cid": EVENT_COMPANY_ID})
                if result.rowcount:
                    print(f"  [seed] {tbl}: {result.rowcount} kayıt event şirketine atandı.")
            # Kullanıcılar: event'e ait olanlar (company_id NULL) → event şirketine
            result = conn.execute(_text(
                "UPDATE users SET company_id = :cid WHERE company_id IS NULL"
            ), {"cid": EVENT_COMPANY_ID})
            if result.rowcount:
                print(f"  [seed] users: {result.rowcount} kullanıcı event şirketine atandı.")
        except Exception as e:
            print(f"  [seed] Event şirketi seed hatası (atlandı): {e}")


# Kanonik tek-tenant şirketi: STOK Mice (operasyonel şirket; 14 kullanıcı +
# faturalar + firma profili burada). Eskiden 00000000-...-0001 ("miceapp Event")
# idi; kazara çoklu-şirket parçalanmasını önlemek için STOK Mice'a sabitlendi.
# desk/database.py EVENT_COMPANY_ID ile AYNI olmalı.
EVENT_COMPANY_ID = "78c37983-7c75-4489-a1ec-c6c1d33f0daf"


if __name__ == "__main__":
    print("Tablolar oluşturuluyor...")
    Base.metadata.create_all(engine)
    print("Seed data ekleniyor...")
    seed_data()
    print("Hazır.")
