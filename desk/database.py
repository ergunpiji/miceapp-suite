"""
Satın Alma — Veritabanı bağlantısı ve başlangıç verisi
"""

import os
from datetime import datetime, date

from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import (
    Base, Company, User, Customer, CashBook,
    GeneralExpenseCategory, LeaveType, PublicHoliday,
    LEAVE_TYPE_DEFAULTS, PayrollSettings, VendorType,
)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

_raw_url = os.environ.get("DATABASE_URL", "sqlite:///./edem.db")
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
_is_sqlite = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 300
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10
    # Railway proxy üzerinden stall'a karşı: TCP keepalive + statement_timeout
    # (yoksa yarım kalan bağlantıda sonsuza dek asılıyor — özellikle uzak DB'de)
    _engine_kwargs["connect_args"] = {
        "connect_timeout": 15,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "options": "-c statement_timeout=120000",   # 120s — tek sorgu bunu aşarsa hata ver
    }

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def seed_data() -> None:
    db = SessionLocal()
    try:
        # Admin kullanıcı
        if db.query(User).count() == 0:
            db.add(User(
                name="Admin",
                email="admin@miceapp.net",
                password_hash=_pwd_ctx.hash("Admin123"),
                role="admin",
                active=True,
            ))
            db.flush()
            print("[seed] Admin kullanıcı eklendi.")

        # Ana Kasa
        if db.query(CashBook).count() == 0:
            db.add(CashBook(name="Ana Kasa", currency="TRY"))
            db.flush()
            print("[seed] Ana Kasa eklendi.")

        # Genel Gider Kategorileri
        if db.query(GeneralExpenseCategory).count() == 0:
            cats = [
                ("Ofis Giderleri", 1, [
                    "Kira", "Elektrik & Doğalgaz", "Su", "İnternet & Telefon",
                    "Temizlik", "Kırtasiye & Sarf",
                ]),
                ("Pazarlama & Temsil", 2, [
                    "Reklam & Tanıtım", "Müşteri Ağırlama", "Fuar & Etkinlik",
                ]),
                ("Ulaşım & Seyahat", 3, [
                    "Yakıt", "Araç Bakım", "Uçak & Tren Bileti", "Konaklama",
                    "Taksi & Transfer",
                ]),
                ("Personel", 4, [
                    "Maaş", "SGK İşveren Payı", "Yan Haklar", "Avans",
                    "Eğitim & Gelişim",
                ]),
                ("Diğer", 5, [
                    "Hukuk & Danışmanlık", "Muhasebe", "Banka Masrafları",
                    "Vergi & Harçlar", "Diğer Giderler",
                ]),
            ]
            for cat_name, sort_order, sub_names in cats:
                parent = GeneralExpenseCategory(
                    name=cat_name, parent_id=None, sort_order=sort_order
                )
                db.add(parent)
                db.flush()
                for i, sub in enumerate(sub_names, 1):
                    db.add(GeneralExpenseCategory(
                        name=sub, parent_id=parent.id, sort_order=i
                    ))
            db.flush()
            print("[seed] Gider kategorileri eklendi.")

        db.commit()
        print("[seed] Tamamlandı.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] HATA: {exc}")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Referans no üretimi: TIP-MUS-YYMM-001
# ---------------------------------------------------------------------------

_EVENT_TYPE_CODES = {
    # Yeni satış modülü kodları
    "yi": "YI",   # Yurt İçi
    "yd": "YD",   # Yurt Dışı
    "tk": "TK",   # Kongre
    "ut": "UT",   # Ürün Tanıtım Toplantısı
    "dk": "DK",   # Danışma Kurulu Toplantısı
    # Eski kodlar (geriye dönük uyumluluk)
    "toplanti": "TOP",
    "konferans": "KON",
    "gala": "GAL",
    "egitim": "EGT",
    "lansman": "LAN",
    "diger": "ETK",
}


def generate_hbf_no(db) -> str:
    from models import HBF
    from datetime import date as _date
    yymm = _date.today().strftime("%y%m")
    prefix = f"HBF-{yymm}-"
    count = db.query(HBF).filter(HBF.hbf_no.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


def generate_ref_no(db, event_type: str, customer_code: str, check_in,
                    company_id: str | None = None) -> str:
    """Referans numarası üretir: TIP-MUS-DDMMYYYY-[a,b,c,...]

    Aynı müşteri + aynı tarih kombinasyonunda ilk iş '-a', ikinci '-b', ... şeklinde devam eder.
    """
    from models import Reference
    tip = _EVENT_TYPE_CODES.get(event_type, "ETK")
    mus = (customer_code or "XXX").upper()[:3]
    if isinstance(check_in, str):
        try:
            check_in = date.fromisoformat(check_in)
        except Exception:
            check_in = date.today()
    ddmmyyyy = check_in.strftime("%d%m%Y")
    base = f"{tip}-{mus}-{ddmmyyyy}"

    q = db.query(Reference).filter(Reference.ref_no.like(f"{base}-%"))
    if company_id:
        q = q.filter(Reference.company_id == company_id)

    for letter in "abcdefghijklmnopqrstuvwxyz":
        candidate = f"{base}-{letter}"
        if not q.filter(Reference.ref_no == candidate).first():
            return candidate
    raise ValueError(f"Aynı müşteri ve tarih için 26'dan fazla referans oluşturulamaz ({base})")


# ---------------------------------------------------------------------------
# Init (DB reset + create + seed)
# ---------------------------------------------------------------------------

def _migrate(engine) -> None:
    """Mevcut tablolara eksik kolonları ekler (basit migration)."""
    from sqlalchemy import text

    # PostgreSQL enum'a yeni değer eklemek ve yeni enum yaratmak transaction dışında yapılmalı
    if not DATABASE_URL.startswith("sqlite"):
        try:
            raw = engine.raw_connection()
            raw.set_isolation_level(0)  # AUTOCOMMIT
            cur = raw.cursor()
            # invoice_status_enum kaldırıldı — invoices.status artık VARCHAR (miceapp suite birleşik sözlük).
            # Bu satır artık gereksiz ve PG18'de orphan enum üzerinde takılıyordu.
            cur.execute("ALTER TYPE cheque_status_enum ADD VALUE IF NOT EXISTS 'iptal'")
            cur.execute("ALTER TYPE hbf_status_enum ADD VALUE IF NOT EXISTS 'mudur_onayladi'")
            cur.execute("ALTER TYPE reference_status_enum ADD VALUE IF NOT EXISTS 'arsiv'")
            # Bordro modülü enum — yoksa oluştur
            cur.execute("""
                DO $$ BEGIN
                    CREATE TYPE payroll_status_enum AS ENUM ('taslak', 'onaylandi', 'odendi');
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$
            """)
            cur.close()
            raw.close()
            print("[migrate] enum değerleri eklendi.")
        except Exception as e:
            print(f"[migrate] enum: {e}")

    migrations = [
        # --- miceapp suite: companies = tenant (SaaS alanları) ---
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS slug VARCHAR(100)",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS plan VARCHAR(20) DEFAULT 'starter'",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_slug ON companies (slug)",
        # --- miceapp suite: invoices uzlaştırma (event ile ortak DB) ---
        # status ENUM→VARCHAR (birleşik sözlük: draft|pending|approved|rejected|partial|paid|cancelled)
        # KOŞULLU: sadece hâlâ enum (USER-DEFINED) ise çevir — aksi halde enum tipi kilidiyle
        # self-deadlock olur ve idempotent kalır (varchar'a çevrildikten sonra no-op).
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='invoices' AND column_name='status'
                       AND data_type='USER-DEFINED') THEN
                ALTER TABLE invoices ALTER COLUMN status TYPE VARCHAR(20) USING status::text;
            END IF;
        END $$""",
        # satış bağı: event requests.id (FK yok — paylaşımlı DB)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS request_id VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS ix_invoices_request_id ON invoices (request_id)",
        # fund_transfers: çoklu para birimi (event'ten — currency→micedesk işini kapatır)
        "ALTER TABLE fund_transfers ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'TRY'",
        # GEÇİCİ (Aşama C'de konsolide): event fund kodu desk FundPool'a rewire edilene dek
        # event'in fund_transfers okumaları çalışsın diye eklenen kolonlar
        "ALTER TABLE fund_transfers ADD COLUMN IF NOT EXISTS fund_request_id VARCHAR(36)",
        "ALTER TABLE fund_transfers ADD COLUMN IF NOT EXISTS related_request_id VARCHAR(36)",
        "ALTER TABLE fund_transfers ADD COLUMN IF NOT EXISTS exchange_rate_try FLOAT DEFAULT 1.0",
        # invoices: event (miceapp) uyumu için denormalize/kolaylık kolonları
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS vendor_name VARCHAR(255) DEFAULT ''",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS vat_amount FLOAT DEFAULT 0.0",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS document_path VARCHAR(500)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS document_name VARCHAR(255)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS due_date DATE",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS items_json TEXT",
        # miceapp paylaşımlı kolon: total_amount + payment_status
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS total_amount FLOAT DEFAULT 0.0",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'unpaid'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS vendor_type VARCHAR(50)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS iban VARCHAR(40)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS tax_no VARCHAR(20)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS tax_office VARCHAR(100)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS address TEXT",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS phone VARCHAR(50)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS email VARCHAR(200)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS payment_term INTEGER DEFAULT 30",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact VARCHAR(200)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS location_type VARCHAR(20) DEFAULT 'turkiye'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS cities TEXT",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS bank_accounts_json TEXT",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT true",
        # VendorPrepayment yeni kolonlar
        "ALTER TABLE vendor_prepayments ADD COLUMN IF NOT EXISTS payment_type VARCHAR(20) DEFAULT 'prepayment'",
        "ALTER TABLE vendor_prepayments ADD COLUMN IF NOT EXISTS ref_id VARCHAR(36)",
        # Customer active alanı
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT true",
        # User is_approver alanı
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approver BOOLEAN DEFAULT false",
        # HBF çoklu referans ve belge ekleri
        "ALTER TABLE hbf_forms ADD COLUMN IF NOT EXISTS refs_json TEXT",
        "ALTER TABLE hbf_forms ADD COLUMN IF NOT EXISTS attachments_json TEXT",
        # EmployeeAdvance avans tipi ve iş avansı kapatma alanları
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS advance_type VARCHAR(10) DEFAULT 'maas'",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS ref_id VARCHAR(36)",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS expense_items_json TEXT",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS cash_return_amount FLOAT DEFAULT 0",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS closed_at DATE",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS closed_by VARCHAR(36)",
        "ALTER TABLE cash_entries ADD COLUMN IF NOT EXISTS category VARCHAR(100)",
        "ALTER TABLE cash_entries ADD COLUMN IF NOT EXISTS related_party VARCHAR(150)",
        # Employee → User bağlantısı
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
        # EmployeeAdvance onay akışı
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) DEFAULT 'onaylandi'",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS requested_by VARCHAR(36)",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS approved_by_id VARCHAR(36)",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS approval_note VARCHAR(300)",
        # payment_method nullable yap (talep aşamasında henüz bilinmez)
        "ALTER TABLE employee_advances ALTER COLUMN payment_method DROP NOT NULL",
        "ALTER TABLE employee_advances ALTER COLUMN advance_date DROP NOT NULL",
        # Çek modülü yeni kolonlar
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS bank_account_id VARCHAR(36)",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS settled_date DATE",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS settled_by VARCHAR(36)",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS attachment VARCHAR(300)",
        # fund_pools, fund_transfers, cash_day_closes tabloları create_all tarafından oluşturulur
        # GM haftalık ödeme listesi kararı — Invoice / Cheque / CreditCardStatement
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gm_decision VARCHAR(20)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gm_decision_at TIMESTAMP",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gm_decision_by VARCHAR(36)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gm_postpone_until DATE",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gm_method_override VARCHAR(20)",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS gm_decision VARCHAR(20)",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS gm_decision_at TIMESTAMP",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS gm_decision_by VARCHAR(36)",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS gm_postpone_until DATE",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS gm_method_override VARCHAR(20)",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS gm_decision VARCHAR(20)",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS gm_decision_at TIMESTAMP",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS gm_decision_by VARCHAR(36)",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS gm_postpone_until DATE",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS gm_method_override VARCHAR(20)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gm_decision_note TEXT",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS gm_decision_note TEXT",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS gm_decision_note TEXT",
        "ALTER TABLE payroll_decisions ADD COLUMN IF NOT EXISTS gm_decision_note TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gm_approved_amount FLOAT",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS gm_approved_amount FLOAT",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS gm_approved_amount FLOAT",
        "ALTER TABLE payroll_decisions ADD COLUMN IF NOT EXISTS gm_approved_amount FLOAT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS preparer_note TEXT",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS preparer_note TEXT",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS preparer_note TEXT",
        "ALTER TABLE payroll_decisions ADD COLUMN IF NOT EXISTS preparer_note TEXT",
        # PaymentInstruction izlenebilirlik FK'lar — payment_instructions tablosu create_all ile oluşur
        "ALTER TABLE invoice_payments ADD COLUMN IF NOT EXISTS instruction_id VARCHAR(36)",
        "ALTER TABLE bank_movements ADD COLUMN IF NOT EXISTS instruction_id VARCHAR(36)",
        "ALTER TABLE cash_entries ADD COLUMN IF NOT EXISTS instruction_id VARCHAR(36)",
        "ALTER TABLE credit_card_txns ADD COLUMN IF NOT EXISTS instruction_id VARCHAR(36)",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS created_by_instruction_id VARCHAR(36)",
        "ALTER TABLE salary_payments ADD COLUMN IF NOT EXISTS instruction_id VARCHAR(36)",
        # User profil bilgileri
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS surname VARCHAR(120)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS title VARCHAR(150)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(40)",
        # ManualPaymentLine referans bağlantısı
        "ALTER TABLE manual_payment_lines ADD COLUMN IF NOT EXISTS ref_id VARCHAR(36)",
        # E-Fatura entegrasyonu (prizma-einvoice paketi)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_status VARCHAR(20)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_uuid VARCHAR(64)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_pdf_url TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_sent_at TIMESTAMP",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_inbox_id VARCHAR(36)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_external_uuid VARCHAR(64)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_efatura_user BOOLEAN",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS efatura_alias VARCHAR(100)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS efatura_checked_at TIMESTAMP",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS is_efatura_user BOOLEAN",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS efatura_alias VARCHAR(100)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS efatura_checked_at TIMESTAMP",
        # Rol sistemi — 5 katmanlı hiyerarşi
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'kullanici'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS manager_id VARCHAR(36)",
        "UPDATE users SET role = 'kullanici' WHERE role IS NULL",
        # HBF iki aşamalı onay kolonları
        "ALTER TABLE hbf_forms ADD COLUMN IF NOT EXISTS manager_approved_by VARCHAR(36)",
        "ALTER TABLE hbf_forms ADD COLUMN IF NOT EXISTS manager_approved_at TIMESTAMP",
        # İzin yönetimi — leave_types, leave_balances, leave_requests, public_holidays
        # tabloları create_all tarafından oluşturulur; ek kolon migration'ları buraya gelir
        "ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS payroll_processed BOOLEAN DEFAULT false",
        # Bordro modülü — employees.is_retired + yeni tablolar create_all ile oluşur
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS is_retired BOOLEAN DEFAULT false",
        "ALTER TABLE payroll_records ADD COLUMN IF NOT EXISTS paid_leave_days FLOAT DEFAULT 0",
        "ALTER TABLE payroll_records ADD COLUMN IF NOT EXISTS sgk_gun INTEGER DEFAULT 30",
        "ALTER TABLE payroll_records ADD COLUMN IF NOT EXISTS fiili_calisma_gun INTEGER DEFAULT 0",
        "ALTER TABLE payroll_records ADD COLUMN IF NOT EXISTS hafta_tatili INTEGER DEFAULT 0",
        "ALTER TABLE payroll_records ADD COLUMN IF NOT EXISTS resmi_tatil_gun INTEGER DEFAULT 0",
        "ALTER TABLE employee_personal_info ADD COLUMN IF NOT EXISTS clothing_size VARCHAR(10)",
        # ── Multi-tenancy ──────────────────────────────────────────────────────
        "CREATE TABLE IF NOT EXISTS companies (id SERIAL PRIMARY KEY, name VARCHAR(200) NOT NULL, short_name VARCHAR(80), tax_no VARCHAR(20), tax_office VARCHAR(100), address VARCHAR(300), phone VARCHAR(40), email VARCHAR(200), logo_path VARCHAR(300), active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP DEFAULT NOW())",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE cash_books ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE cash_day_closes ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE cash_entries ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE bank_accounts ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE bank_movements ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE credit_cards ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE credit_card_statements ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE credit_card_txns ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE cheques ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)',
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE invoice_payments ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE vendor_prepayments ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE manual_payment_lines ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE payment_instructions ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE general_expense_categories ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE general_expenses ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE employee_personal_info ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE employee_assets ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE employee_documents ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE employee_career_events ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE salary_payments ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE employee_benefits ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE payroll_records ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE payroll_decisions ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE payroll_settings ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE annual_budgets ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE budget_lines ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE fixed_expenses ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE hbf_forms ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE leave_balances ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE fund_pools ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        "ALTER TABLE fund_transfers ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id)",
        # Index'ler — en yoğun kullanılan tablolar
        "CREATE INDEX IF NOT EXISTS idx_invoices_company ON invoices(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_employees_company ON employees(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_leave_requests_company ON leave_requests(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_employee_advances_company ON employee_advances(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_hbf_forms_company ON hbf_forms(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_payment_instructions_company ON payment_instructions(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_payroll_records_company ON payroll_records(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_general_expenses_company ON general_expenses(company_id)",
        # Tedarikçi tipleri yönetim tablosu
        "CREATE TABLE IF NOT EXISTS vendor_types (id SERIAL PRIMARY KEY, value VARCHAR(50) NOT NULL UNIQUE, label VARCHAR(100) NOT NULL, sort_order INTEGER DEFAULT 0, active BOOLEAN DEFAULT TRUE)",
        # Fatura → Müşteri bağlantısı (kesilen fatura için)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_id VARCHAR(36) REFERENCES customers(id)",
        # Müşteri tahsilat ayarları + eski şemada eksik kolonlar
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS payment_term VARCHAR(100)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS payment_dow INTEGER",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS contacts_json TEXT DEFAULT '[]'",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS docs_json TEXT DEFAULT '[]'",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS excel_template_path VARCHAR(500) DEFAULT ''",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS excel_template_b64 TEXT DEFAULT ''",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS excel_config_json TEXT DEFAULT '{}'",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS sector VARCHAR(100)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_no VARCHAR(30)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_office VARCHAR(100)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS address TEXT",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS email VARCHAR(200)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS phone VARCHAR(50)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS code VARCHAR(10)",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS team_id VARCHAR(36)",
        # Fatura eki ve tahsilat tarihi
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS attachment_path VARCHAR",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS collection_date DATE",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(36) REFERENCES users(id)",
        "ALTER TABLE hbf_forms ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        "ALTER TABLE hbf_forms ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(36) REFERENCES users(id)",
        # Şirket onay limitleri
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS ref_close_limit_kullanici FLOAT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS ref_close_limit_mudur FLOAT",
        # Referans kapanış onay akışı ("references" PostgreSQL'de rezerve kelime — tırnak zorunlu)
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS approval_status VARCHAR(30)',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS approval_requested_by VARCHAR(36) REFERENCES users(id)',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS approval_requested_at TIMESTAMP',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS mudur_approved_by VARCHAR(36) REFERENCES users(id)',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS mudur_approved_at TIMESTAMP',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS gm_approved_by VARCHAR(36) REFERENCES users(id)',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS gm_approved_at TIMESTAMP',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS approval_rejection_note TEXT',
        # Referans aktifleştirme talebi
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS reactivation_requested_by VARCHAR(36) REFERENCES users(id)',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS reactivation_requested_at TIMESTAMP',
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS reactivation_note TEXT',
        # Logo ve SystemSetting TEXT kolonları (base64 için alan genişletme)
        "ALTER TABLE companies ALTER COLUMN logo_path TYPE TEXT",
        "ALTER TABLE system_settings ALTER COLUMN value TYPE TEXT",
        # Müşteri ön tahsilat tablosu
        'CREATE TABLE IF NOT EXISTS customer_prepayments (id SERIAL PRIMARY KEY, company_id VARCHAR(36) REFERENCES companies(id), customer_id VARCHAR(36) NOT NULL REFERENCES customers(id), payment_type VARCHAR(20) NOT NULL DEFAULT \'prepayment\', ref_id VARCHAR(36) REFERENCES "references"(id), payment_date DATE NOT NULL, amount FLOAT NOT NULL, payment_method VARCHAR(20) NOT NULL, bank_account_id VARCHAR(36) REFERENCES bank_accounts(id), cash_book_id VARCHAR(36) REFERENCES cash_books(id), cheque_id VARCHAR(36) REFERENCES cheques(id), notes VARCHAR(300), created_by VARCHAR(36) REFERENCES users(id), created_at TIMESTAMP DEFAULT NOW())',
        # Bildirimler tablosu
        "CREATE TABLE IF NOT EXISTS notifications (id SERIAL PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id), notif_type VARCHAR(30) NOT NULL DEFAULT 'info', title VARCHAR(200) NOT NULL, message VARCHAR(500), link VARCHAR(300), ref_id VARCHAR(36), read_at TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)",
        # PayrollSettings: yıl bazlı unique'i kaldır, (yıl, şirket) bazlı unique'e geç
        "ALTER TABLE payroll_settings DROP CONSTRAINT IF EXISTS payroll_settings_year_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_settings_year_company ON payroll_settings(year, company_id)",
        # Demo şirket alanları
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS demo_reset_at TIMESTAMP",
        # ── RBAC v2 — Departman bazlı erişim kontrolü ─────────────────────
        # departments, user_departments, module_access tabloları create_all ile oluşur
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36) REFERENCES users(id)",
        'ALTER TABLE "references" ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36) REFERENCES users(id)',
        "CREATE INDEX IF NOT EXISTS idx_customers_owner ON customers(owner_id)",
        'CREATE INDEX IF NOT EXISTS idx_references_owner ON "references"(owner_id)',
        # Referans owner_id backfill: created_by → owner_id (NULL kalanlar için)
        'UPDATE "references" SET owner_id = created_by WHERE owner_id IS NULL AND created_by IS NOT NULL',
        # Sales departmanı için invoices.can_edit=False (fatura sadece muhasebe/GM girer)
        "UPDATE module_access SET can_edit = false "
        "WHERE module_key = 'invoices' "
        "AND department_id::text IN (SELECT id::text FROM departments WHERE key = 'sales')",
        # Çok kademeli fatura onay akışı (temsilci → müdür → GM)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approval_status VARCHAR(30)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS current_approver_id VARCHAR(36) REFERENCES users(id)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approval_history TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approval_rejection_note TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS is_split_parent BOOLEAN DEFAULT FALSE",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS split_parent_id VARCHAR(36) REFERENCES invoices(id)",
        # miceapp ile paylaşımlı: invoices.request_id miceapp tarafından kullanılır
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS request_id VARCHAR(36)",
        # Koordinatör onay akışı (miceapp ↔ micedesk köprüsü)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_status VARCHAR(20)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_note TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_reviewed_at TIMESTAMP",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_reviewed_by VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_approver ON invoices(current_approver_id) WHERE current_approver_id IS NOT NULL",
        # Eski fatura kayıtları onay akışından geçmediği için approval_status='approved' kabul edilir
        "UPDATE invoices SET approval_status = 'approved' WHERE approval_status IS NULL AND status IN ('approved','partial','paid')",
        # ── Vendor (birleşik tablo: financial_vendors → vendors) ──────────────
        # Yeni vendors tablosuna yeni sütunlar ekle (create_all henüz yoksa oluşturur)
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS supplier_type VARCHAR(50) DEFAULT 'diger'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS city VARCHAR(100) DEFAULT ''",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS cities_json TEXT DEFAULT '[]'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS location_type VARCHAR(20) DEFAULT 'turkiye'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact VARCHAR(200) DEFAULT ''",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contacts_json TEXT DEFAULT '[]'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS website VARCHAR(255) DEFAULT ''",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS stars INTEGER",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS total_rooms INTEGER DEFAULT 0",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS halls_json TEXT DEFAULT '[]'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS docs_json TEXT DEFAULT '[]'",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS created_by VARCHAR(36)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS is_efatura_user BOOLEAN",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS efatura_alias VARCHAR(100)",
        "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS efatura_checked_at TIMESTAMP",
        # FK'ları vendors tablosuna taşı (eskiden financial_vendors'a bakıyordu)
        # PostgreSQL: mevcut FK kısıtlamaları DROP/ADD ile güncellenemez — sadece yeni tabloda geçerli
        # invoices, cheques, vendor_prepayments, general_expenses tabloları vendor_id FK artık vendors'a bakıyor
        # SQLAlchemy create_all yeni tablolarda doğru FK oluşturur; eski kayıtlar etkilenmez
        # ── Satış modülü ──────────────────────────────────────────────────────
        # Ortak havuz: referanssız gelen faturalar satışçı sahiplenene kadar burada bekler
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS in_pool BOOLEAN NOT NULL DEFAULT FALSE",
        # ref_no sütununu genişlet: yeni format YI-ABC-15052026-a = 17 karakter, VARCHAR(40) yeterli
        'ALTER TABLE "references" ALTER COLUMN ref_no TYPE VARCHAR(40)',
        # ── module_access / user_departments tip düzeltmesi ───────────────────
        # Eski DB'lerde id ve department_id INTEGER SERIAL — model VARCHAR(36) bekliyor.
        # Mevcut integer değerleri ('1','2'..) string'e cast edilir; UUID'ler doğrudan girer.
        "ALTER TABLE module_access DROP CONSTRAINT IF EXISTS module_access_pkey",
        "ALTER TABLE module_access ALTER COLUMN id TYPE VARCHAR(36) USING id::VARCHAR",
        "ALTER TABLE module_access ADD PRIMARY KEY (id)",
        "ALTER TABLE module_access DROP CONSTRAINT IF EXISTS module_access_department_id_fkey",
        "ALTER TABLE module_access ALTER COLUMN department_id TYPE VARCHAR(36) USING department_id::VARCHAR",
        "ALTER TABLE user_departments DROP CONSTRAINT IF EXISTS user_departments_pkey",
        "ALTER TABLE user_departments ALTER COLUMN department_id TYPE VARCHAR(36) USING department_id::VARCHAR",
        "ALTER TABLE user_departments ADD PRIMARY KEY (user_id, department_id)",
        "ALTER TABLE user_departments DROP CONSTRAINT IF EXISTS user_departments_department_id_fkey",
        # ── user_departments.department_id dönüşümü — DÜZELTME ───────────────
        # Yukarıdaki ALTER COLUMN, FK kısıtlaması (→ departments.id INTEGER) varken başarısız oluyordu.
        # Doğru sıra: önce FK'yı düşür, sonra tür değiştir. Bu blok idempotent; zaten VARCHAR ise
        # ALTER COLUMN hata alır fakat görmezden gelinir.
        "ALTER TABLE user_departments DROP CONSTRAINT IF EXISTS user_departments_department_id_fkey",
        "ALTER TABLE user_departments DROP CONSTRAINT IF EXISTS user_departments_pkey",
        "ALTER TABLE user_departments ALTER COLUMN department_id TYPE VARCHAR(36) USING department_id::VARCHAR",
        "ALTER TABLE user_departments ADD PRIMARY KEY (user_id, department_id)",
        # ── departments.id INTEGER → VARCHAR(36) ─────────────────────────────
        # user_departments.department_id artık VARCHAR ama departments.id hâlâ INTEGER →
        # JOIN departments ON departments.id = user_departments_1.department_id başarısız.
        # module_access/user_departments FK'ları zaten kaldırıldı; departments PK yeniden oluşturulur.
        "ALTER TABLE departments DROP CONSTRAINT IF EXISTS departments_pkey",
        "ALTER TABLE departments ALTER COLUMN id TYPE VARCHAR(36) USING id::VARCHAR",
        "ALTER TABLE departments ADD PRIMARY KEY (id)",
    ]

    # --- Eski schema type-cast düzeltmeleri ---
    # Yalnızca VARCHAR PK'ya referans veren FK sütunları VARCHAR'a dönüştürülür.
    # INTEGER PK'ya referans veren FK sütunları INTEGER kalmalı; yanlış dönüştürüldüyse geri al.

    # 1) vendors.id zaten VARCHAR(36): vendor_id FK'ları da VARCHAR olmalı
    _vendor_fk_drops = [
        "ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_vendor_id_fkey",
        "ALTER TABLE cheques DROP CONSTRAINT IF EXISTS cheques_vendor_id_fkey",
    ]
    for _sql in _vendor_fk_drops:
        try:
            with engine.begin() as _tc:
                _tc.execute(text(_sql))
        except Exception:
            pass
    _vendor_casts = [
        "ALTER TABLE public_holidays ALTER COLUMN id TYPE VARCHAR(36) USING id::text",
        "ALTER TABLE invoices ALTER COLUMN vendor_id TYPE VARCHAR(36) USING vendor_id::text",
        "ALTER TABLE cheques ALTER COLUMN vendor_id TYPE VARCHAR(36) USING vendor_id::text",
    ]
    for _sql in _vendor_casts:
        try:
            with engine.begin() as _tc:
                _tc.execute(text(_sql))
        except Exception:
            pass

    # 2) invoices.id hâlâ INTEGER: invoice_payments.invoice_id ve diğer FK'lar INTEGER kalmalı.
    #    Yanlışlıkla VARCHAR'a dönüştürüldüyse geri al.
    _int_reverts = [
        "ALTER TABLE invoice_payments ALTER COLUMN invoice_id TYPE INTEGER USING invoice_id::integer",
        "ALTER TABLE invoices ALTER COLUMN customer_id TYPE INTEGER USING customer_id::integer",
        "ALTER TABLE invoices ALTER COLUMN ref_id TYPE INTEGER USING ref_id::integer",
        "ALTER TABLE general_expenses ALTER COLUMN ref_id TYPE INTEGER USING ref_id::integer",
    ]
    for _sql in _int_reverts:
        try:
            with engine.begin() as _tc:
                _tc.execute(text(_sql))
        except Exception:
            pass  # Zaten INTEGER veya dönüşüm başarısız — geç
    with engine.begin() as conn:
        for sql in migrations:
            try:
                import os as _os
                if _os.environ.get("MIG_DEBUG"): print(f"[mig-dbg] {sql[:55]}", flush=True)
                conn.execute(text(sql))
            except Exception as e:
                print(f"[migrate] {sql[:60]}… → {e}")


def _seed_extra_categories() -> None:
    """Eksik ana/alt kategorileri idempotent olarak ekler."""
    extra = [
        ("Personel (*)", 6, [
            "Bordro", "Elden", "Yan Haklar", "Sigorta", "Overtime",
            "Tazminat", "İkramiye/Prim", "Yönetim", "İsg & Eğitim",
            "Kıyafet", "Teşvik",
        ]),
        ("Genel Giderler", 7, [
            "Ofis Kira", "Ofis Gider", "Depo Kira", "Depo Gider",
            "Sigorta", "Araç", "Ulaşım", "İletişim", "It - Software",
            "It - Malzeme", "Temsil & Ağırlama", "Tanıtım", "Danışmanlık",
            "Resmi", "Bağış & Aidat", "Operasyonel Harcamalar",
        ]),
        ("Finans Giderleri", 8, [
            "Faiz", "Ortaklar Faizi", "Kredi Komisyonları", "Masraf",
        ]),
    ]
    db = SessionLocal()
    try:
        changed = False
        for cat_name, sort_order, sub_names in extra:
            parent = db.query(GeneralExpenseCategory).filter_by(
                name=cat_name, parent_id=None
            ).first()
            if not parent:
                parent = GeneralExpenseCategory(
                    name=cat_name, parent_id=None, sort_order=sort_order
                )
                db.add(parent)
                db.flush()
                changed = True
            for i, sub in enumerate(sub_names, 1):
                exists = db.query(GeneralExpenseCategory).filter_by(
                    name=sub, parent_id=parent.id
                ).first()
                if not exists:
                    db.add(GeneralExpenseCategory(
                        name=sub, parent_id=parent.id, sort_order=i
                    ))
                    changed = True
        if changed:
            db.commit()
            print("[seed] Ek gider kategorileri eklendi.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] Ek kategoriler HATA: {exc}")
    finally:
        db.close()


def _seed_leave_types() -> None:
    """Varsayılan izin türlerini idempotent olarak ekler."""
    db = SessionLocal()
    try:
        changed = False
        for code, name, is_paid, req_bal, req_rep, def_days, color, sort in LEAVE_TYPE_DEFAULTS:
            existing = db.query(LeaveType).filter_by(code=code).first()
            if not existing:
                db.add(LeaveType(
                    code=code, name=name, is_paid=is_paid,
                    requires_balance=req_bal, requires_report=req_rep,
                    default_days=def_days, color=color, sort_order=sort,
                ))
                changed = True
        if changed:
            db.commit()
            print("[seed] İzin türleri eklendi.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] İzin türleri HATA: {exc}")
    finally:
        db.close()


def _fix_kurban_2026() -> None:
    """Yanlış tarihe (25-29 Mayıs) kaydedilmiş Kurban Bayramı kayıtlarını siler."""
    from datetime import date as _date
    wrong_dates = [_date(2026, 5, 25), _date(2026, 5, 26), _date(2026, 5, 27),
                   _date(2026, 5, 28), _date(2026, 5, 29)]
    db = SessionLocal()
    try:
        rows = db.query(PublicHoliday).filter(
            PublicHoliday.date.in_(wrong_dates),
            PublicHoliday.name.like("Kurban Bayramı%"),
        ).all()
        if rows:
            for r in rows:
                db.delete(r)
            db.commit()
            print(f"[migrate] {len(rows)} yanlış Kurban Bayramı kaydı silindi.")
    except Exception as exc:
        db.rollback()
        print(f"[migrate] Kurban Bayramı düzeltme HATA: {exc}")
    finally:
        db.close()


def _seed_public_holidays_2026() -> None:
    """2026 Türkiye resmi tatillerini idempotent olarak ekler."""
    from datetime import date as _date
    holidays = [
        (_date(2026, 1, 1),   "Yılbaşı",                                    False),
        (_date(2026, 3, 19),  "Ramazan Bayramı Arife",                       True),
        (_date(2026, 3, 20),  "Ramazan Bayramı 1. Günü",                     False),
        (_date(2026, 3, 21),  "Ramazan Bayramı 2. Günü",                     False),
        (_date(2026, 3, 22),  "Ramazan Bayramı 3. Günü",                     False),
        (_date(2026, 4, 23),  "Ulusal Egemenlik ve Çocuk Bayramı",           False),
        (_date(2026, 5, 1),   "Emek ve Dayanışma Bayramı",                   False),
        (_date(2026, 5, 19),  "Atatürk'ü Anma, Gençlik ve Spor Bayramı",    False),
        (_date(2026, 5, 26),  "Kurban Bayramı Arife",                        True),
        (_date(2026, 5, 27),  "Kurban Bayramı 1. Günü",                      False),
        (_date(2026, 5, 28),  "Kurban Bayramı 2. Günü",                      False),
        (_date(2026, 5, 29),  "Kurban Bayramı 3. Günü",                      False),
        (_date(2026, 5, 30),  "Kurban Bayramı 4. Günü",                      False),
        (_date(2026, 7, 15),  "Demokrasi ve Milli Birlik Günü",              False),
        (_date(2026, 8, 30),  "Zafer Bayramı",                               False),
        (_date(2026, 10, 28), "Cumhuriyet Bayramı Arife",                    True),
        (_date(2026, 10, 29), "Cumhuriyet Bayramı",                          False),
    ]
    db = SessionLocal()
    try:
        changed = False
        for hdate, hname, is_half in holidays:
            if not db.query(PublicHoliday).filter_by(date=hdate).first():
                db.add(PublicHoliday(date=hdate, name=hname, is_half=is_half))
                changed = True
        if changed:
            db.commit()
            print("[seed] 2026 resmi tatilleri eklendi.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] Resmi tatiller HATA: {exc}")
    finally:
        db.close()


def _seed_default_company() -> None:
    """Multi-tenancy: varsayılan şirketi oluştur ve mevcut kayıtları ona bağla.
    Backfill (NULL → cid) her başlatmada çalışır — idempotent."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        existing = db.query(Company).first()
        if existing is None:
            company = Company(name="Prizmatik Teknik Dekor", active=True)
            db.add(company)
            db.flush()
            cid = company.id
            db.commit()
            print(f"[seed] Default şirket oluşturuldu: id={cid}")
        else:
            cid = existing.id

        # NULL olan tüm satırları default şirkete bağla (idempotent — her başlatmada).
        # Migration başarısız olmuş tablolar burada telafi edilir.
        BACKFILL_TABLES = [
            "users", "customers", "vendors", "cash_books", "cash_day_closes",
            "cash_entries", "bank_accounts", "bank_movements", "credit_cards",
            "credit_card_statements", "credit_card_txns", "cheques", '"references"',
            "invoices", "invoice_payments", "vendor_prepayments", "manual_payment_lines",
            "payment_instructions", "general_expense_categories", "general_expenses",
            "employees", "employee_personal_info", "employee_assets", "employee_documents",
            "employee_career_events", "salary_payments", "employee_benefits",
            "employee_advances", "payroll_records", "payroll_decisions", "payroll_settings",
            "annual_budgets", "budget_lines", "fixed_expenses", "hbf_forms",
            "leave_balances", "leave_requests", "fund_pools", "fund_transfers",
        ]
        for tbl in BACKFILL_TABLES:
            try:
                db.execute(text(f"UPDATE {tbl} SET company_id = {cid} WHERE company_id IS NULL"))
            except Exception:
                db.rollback()
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[seed] Default şirket HATA: {exc}")
    finally:
        db.close()


DEFAULT_DEPARTMENTS = [
    {
        "key": "sales", "name": "Satış", "color": "#3b82f6", "icon": "bi-briefcase",
        "modules": {
            "customers": (True, True), "references": (True, True),
            "invoices": (True, False),    # faturaları görür ama yeni fatura giremez
            "sales_requests": (True, True),  # kesilen fatura taleplerini yönetir
        },
    },
    {
        "key": "accounting", "name": "Muhasebe", "color": "#16a34a", "icon": "bi-calculator",
        "modules": {
            "customers": (True, True), "invoices": (True, True),
            "references": (True, False),  # görür ama yeni açamaz/düzenleyemez
            "cash": (True, True), "banks": (True, True),
            "cheques": (True, True), "credit_cards": (True, True),
            "vendors": (True, True), "general_expenses": (True, True),
            "fund_pools": (True, True), "budgets": (True, True),
            "payments_weekly": (True, True), "payment_instructions": (True, True),
            "advances": (True, False), "hbf": (True, False),
            "reports_financial": (True, False), "tax_reports": (True, False),
            "edefter": (True, False), "einvoice": (True, True),
            "sales_requests": (True, True),  # satış fatura taleplerini işler
        },
    },
    {
        "key": "hr", "name": "İnsan Kaynakları", "color": "#f59e0b", "icon": "bi-people",
        "modules": {
            "employees": (True, True), "leaves": (True, True),
            "advances": (True, True), "hbf": (True, True),
            "bordro": (True, True), "reports_hr": (True, False),
        },
    },
    {
        "key": "operations", "name": "Operasyon", "color": "#8b5cf6", "icon": "bi-diagram-3",
        "modules": {
            "references": (True, True), "customers": (True, False),
            "invoices": (True, False), "vendors": (True, True),
        },
    },
]


def _seed_departments_and_access() -> None:
    """Her şirket için 4 default departman + modül erişim matrisi.
    Idempotent: var olan key'leri tekrar yaratmaz."""
    from models import Department, ModuleAccess
    from sqlalchemy import text
    db = SessionLocal()
    try:
        companies = db.query(Company).all()
        for company in companies:
            existing_depts = {
                d.key: d for d in db.query(Department).filter_by(company_id=company.id).all()
            }
            for dept_def in DEFAULT_DEPARTMENTS:
                dept = existing_depts.get(dept_def["key"])
                if dept is None:
                    dept = Department(
                        company_id=company.id,
                        key=dept_def["key"],
                        name=dept_def["name"],
                        color=dept_def["color"],
                        icon=dept_def["icon"],
                        active=True,
                    )
                    db.add(dept)
                    db.flush()
                # Var olan veya yeni — eksik modül erişim kayıtlarını ekle
                # (admin elle değiştirdiyse mevcut kayıtlara DOKUNMA)
                existing_modules = {
                    ma.module_key
                    for ma in db.query(ModuleAccess).filter(
                        ModuleAccess.department_id == str(dept.id)
                    ).all()
                }
                for module_key, (can_view, can_edit) in dept_def["modules"].items():
                    if module_key in existing_modules:
                        continue
                    # Raw SQL kullan: id sütunu dahil edilmez → DB otomatik üretir.
                    # Migrasyon sonrası department_id VARCHAR(36) olduğundan UUID ve int değerleri kabul eder.
                    db.execute(
                        text("INSERT INTO module_access (department_id, module_key, can_view, can_edit)"
                             " VALUES (:did, :mk, :cv, :ce)"),
                        {"did": str(dept.id), "mk": module_key, "cv": can_view, "ce": can_edit},
                    )
            db.commit()
        print("[seed] Departman ve modül erişim matrisi hazır.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] Departman seed HATA: {exc}")
    finally:
        db.close()


def _seed_demo_company() -> None:
    """Demo A.Ş. şirketini ve örnek verilerini oluşturur — idempotent."""
    from models import (
        Invoice, InvoicePayment, Reference, Customer, FinancialVendor,
        Employee, HBF, LeaveRequest, LeaveType, CashBook,
    )
    db = SessionLocal()
    try:
        demo = db.query(Company).filter_by(name="Demo A.Ş.").first()
        if demo is None:
            demo = Company(name="Demo A.Ş.", short_name="DEMO",
                           email="demo@prizmadesk.com", is_demo=True,
                           demo_reset_at=datetime.utcnow())
            db.add(demo)
            db.flush()
            print(f"[seed] Demo şirket oluşturuldu: id={demo.id}")

        cid = str(demo.id)  # vendors.company_id VARCHAR — integer karşılaştırma hatası önlenir

        # Demo admin kullanıcı
        demo_user = db.query(User).filter_by(email="demo@prizmadesk.com").first()
        if demo_user is None:
            demo_user = User(
                name="Demo", surname="Kullanıcı",
                email="demo@prizmadesk.com",
                password_hash=_pwd_ctx.hash("Demo123"),
                role="admin", company_id=cid, active=True,
            )
            db.add(demo_user)
            db.flush()

        # Genel admin kullanıcısını da Demo A.Ş.'ye bağla (company_id yoksa)
        generic_admin = db.query(User).filter_by(email="admin@miceapp.net").first()
        if generic_admin and not generic_admin.company_id:
            generic_admin.company_id = cid
            db.flush()

        # Kasa
        kasa = db.query(CashBook).filter_by(company_id=cid).first()
        if kasa is None:
            kasa = CashBook(name="Ana Kasa", currency="TRY", company_id=cid)
            db.add(kasa)
            db.flush()

        # Müşteriler
        if db.query(Customer).filter_by(company_id=cid).count() == 0:
            for c in [
                Customer(name="ABC Tekstil A.Ş.", code="ABC",
                         tax_no="1234567890", company_id=cid),
                Customer(name="XYZ Gıda Ltd. Şti.", code="XYZ",
                         tax_no="9876543210", company_id=cid),
            ]:
                db.add(c)
            db.flush()

        # Tedarikçiler
        if db.query(FinancialVendor).filter_by(company_id=cid).count() == 0:
            for v in [
                FinancialVendor(name="Ofis Malzeme A.Ş.", tax_no="1111111111",
                                company_id=cid),
                FinancialVendor(name="Temizlik Hiz. Ltd.", tax_no="2222222222",
                                company_id=cid),
            ]:
                db.add(v)
            db.flush()

        # Çalışan
        if db.query(Employee).filter_by(company_id=cid).count() == 0:
            emp = Employee(
                name="Ayşe Yılmaz", title="Muhasebe Uzmanı",
                department="Finans", start_date=date(2023, 1, 15),
                gross_salary=35000.0, net_salary=28500.0,
                company_id=cid,
            )
            db.add(emp)
            db.flush()

        db.commit()
        print(f"[seed] Demo A.Ş. hazır (id={cid}).")
    except Exception as exc:
        db.rollback()
        print(f"[seed] Demo şirket HATA: {exc}")
    finally:
        db.close()


def _seed_approval_limits() -> None:
    """Fatura onay limitleri default değerleri (TL, KDV dahil).
    Idempotent: SystemSetting'ta yoksa ekler, varsa dokunmaz.
    Admin /admin/approval-limits sayfasından değiştirir."""
    from models import SystemSetting
    defaults = {
        "invoice_approval_limit_kullanici":    "50000",       # 50K TL
        "invoice_approval_limit_mudur":        "250000",      # 250K TL
        "invoice_approval_limit_genel_mudur":  "999999999",   # ~sınırsız
    }
    db = SessionLocal()
    try:
        for key, value in defaults.items():
            row = db.query(SystemSetting).filter_by(key=key).first()
            if row is None:
                db.add(SystemSetting(key=key, value=value))
        db.commit()
        print("[seed] Onay limitleri hazır.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] Onay limitleri HATA: {exc}")
    finally:
        db.close()


def _seed_rbac_test_users() -> None:
    """RBAC v2 test için Demo A.Ş.'ye departman bazlı kullanıcılar ekler.
    Tüm parolalar: Demo123 — idempotent.

    Test kullanıcıları:
      satis@demo.com         — Satış (kullanici rolü)
      satis.mudur@demo.com   — Satış müdürü (mudur rolü, is_head)
      muhasebe@demo.com      — Muhasebe (kullanici)
      muhasebe.mudur@demo.com — Muhasebe müdürü (mudur, is_head)
      ik@demo.com            — İK (kullanici)
      gm@demo.com            — Genel Müdür (departmansız, bypass)
    """
    from models import (
        Customer, FinancialVendor, Employee, Department, UserDepartment, Reference,
    )
    db = SessionLocal()
    try:
        demo = db.query(Company).filter_by(name="Demo A.Ş.").first()
        if demo is None:
            print("[seed-rbac] Demo A.Ş. yok, atlanıyor.")
            return
        cid = str(demo.id)  # vendors.company_id VARCHAR — integer cast

        # Departmanları al (seed sırasında zaten oluşmuş olmalı)
        depts = {
            d.key: d for d in
            db.query(Department).filter_by(company_id=cid).all()
        }
        if not depts:
            print("[seed-rbac] Departmanlar henüz oluşmamış, atlanıyor.")
            return

        # ───────── Test kullanıcıları ─────────
        # (email, ad, soyad, ünvan, rol, departman_keys, is_head_dept, manager_email)
        TEST_USERS = [
            ("satis@demo.com",          "Ahmet",  "Satışçı",  "Satış Temsilcisi",       "kullanici",    ["sales"],      None,         "satis.mudur@demo.com"),
            ("satis.mudur@demo.com",    "Bülent", "Satış",    "Satış Müdürü",           "mudur",        ["sales"],      "sales",      "gm@demo.com"),
            ("muhasebe@demo.com",       "Canan",  "Muhasebe", "Muhasebe Uzmanı",        "kullanici",    ["accounting"], None,         "muhasebe.mudur@demo.com"),
            ("muhasebe.mudur@demo.com", "Deniz",  "Aydın",    "Muhasebe Müdürü",        "mudur",        ["accounting"], "accounting", "gm@demo.com"),
            ("ik@demo.com",             "Elif",   "İK",       "İnsan Kaynakları Uzmanı","kullanici",    ["hr"],         None,         "gm@demo.com"),
            ("gm@demo.com",             "Fatih",  "Yönetici", "Genel Müdür",            "genel_mudur",  [],             None,         None),
        ]

        for email, name, surname, title, role, dept_keys, head_dept, _mgr_email in TEST_USERS:
            u = db.query(User).filter_by(email=email).first()
            if u is None:
                u = User(
                    name=name, surname=surname, title=title,
                    email=email,
                    password_hash=_pwd_ctx.hash("Demo123"),
                    role=role, company_id=cid, active=True,
                )
                db.add(u)
                db.flush()
                print(f"[seed-rbac] User oluşturuldu: {email} ({role})")
            # Departman atamalarını idempotent yenile
            db.query(UserDepartment).filter_by(user_id=u.id).delete()
            for dk in dept_keys:
                dept = depts.get(dk)
                if dept:
                    db.add(UserDepartment(
                        user_id=u.id,
                        department_id=dept.id,
                        is_head=(dk == head_dept),
                    ))
        db.commit()

        # Manager zinciri (HBF/avans/izin önce müdüre, sonra GM'e gider)
        all_users = {
            uu.email: uu for uu in
            db.query(User).filter_by(company_id=cid).all()
        }
        for email, _, _, _, _, _, _, mgr_email in TEST_USERS:
            if not mgr_email:
                continue
            u = all_users.get(email)
            mgr = all_users.get(mgr_email)
            if u and mgr and u.manager_id != mgr.id:
                u.manager_id = mgr.id
        db.commit()

        # ───────── Müşteriler ─────────
        satis_user = db.query(User).filter_by(email="satis@demo.com").first()
        muhasebe_user = db.query(User).filter_by(email="muhasebe@demo.com").first()
        admin_user = db.query(User).filter_by(email="demo@prizmadesk.com").first()
        owner_satis = satis_user.id if satis_user else None
        owner_muh = muhasebe_user.id if muhasebe_user else None
        owner_admin = admin_user.id if admin_user else None

        # Mevcut müşterilere owner ata
        existing_customers = db.query(Customer).filter_by(company_id=cid).all()
        for idx, c in enumerate(existing_customers):
            if c.owner_id is None:
                # ABC → satis, XYZ → satis  (varolan 2 müşteri)
                c.owner_id = owner_satis or owner_admin

        # Ek müşteriler (idempotent: code ile kontrol)
        TEST_CUSTOMERS = [
            ("DEF Lojistik Ltd.",      "DEF", "5555555555", owner_muh),
            ("GHI Yazılım A.Ş.",       "GHI", "6666666666", owner_satis),
            ("JKL İnşaat",             "JKL", "7777777777", owner_admin),
        ]
        for name, code, tax_no, owner_id in TEST_CUSTOMERS:
            if not db.query(Customer).filter_by(company_id=cid, code=code).first():
                db.add(Customer(
                    name=name, code=code, tax_no=tax_no,
                    company_id=cid, owner_id=owner_id, active=True,
                ))
        db.commit()

        # ───────── Tedarikçiler ─────────
        existing_vendor_names = {
            v.name for v in db.query(FinancialVendor).filter_by(company_id=cid).all()
        }
        TEST_VENDORS = [
            ("Yazılım Lisans A.Ş.", "3333333333"),
            ("Kargo Lojistik Ltd.", "4444444444"),
            ("Reklam Ajansı Ltd.",  "5544332211"),
        ]
        for name, tax_no in TEST_VENDORS:
            if name not in existing_vendor_names:
                db.add(FinancialVendor(
                    name=name, tax_no=tax_no, company_id=cid,
                ))
        db.commit()

        # ───────── Çalışanlar ─────────
        # Her test user'a Employee kaydı bağla (izin/avans/HBF talebi için zorunlu).
        # Email → (full_name, title, department, start_date, gross, net)
        USER_EMPLOYEE_MAP = {
            "satis@demo.com":          ("Ahmet Satışçı",  "Satış Temsilcisi",        "Satış",            date(2024, 1, 15), 40000.0, 32000.0),
            "satis.mudur@demo.com":    ("Bülent Satış",   "Satış Müdürü",            "Satış",            date(2022, 5, 1),  60000.0, 47000.0),
            "muhasebe@demo.com":       ("Canan Muhasebe", "Muhasebe Uzmanı",         "Muhasebe",         date(2023, 3, 1),  42000.0, 33500.0),
            "muhasebe.mudur@demo.com": ("Deniz Aydın",    "Muhasebe Müdürü",         "Muhasebe",         date(2021, 9, 15), 65000.0, 50800.0),
            "ik@demo.com":             ("Elif İK",        "İnsan Kaynakları Uzmanı", "İnsan Kaynakları", date(2023, 6, 1),  41000.0, 32700.0),
            "gm@demo.com":             ("Fatih Yönetici", "Genel Müdür",             "Yönetim",          date(2020, 1, 1),  90000.0, 70000.0),
        }
        for email, (full_name, title, dept, sd, gross, net) in USER_EMPLOYEE_MAP.items():
            user_obj = all_users.get(email)
            if not user_obj:
                continue
            emp = db.query(Employee).filter_by(user_id=user_obj.id).first()
            if not emp:
                emp = Employee(
                    name=full_name, title=title, department=dept,
                    start_date=sd, gross_salary=gross, net_salary=net,
                    company_id=cid, user_id=user_obj.id,
                )
                db.add(emp)
        db.commit()

        # ───────── Referanslar (sales user'a atanmış) ─────────
        if satis_user:
            existing_ref_count = db.query(Reference).filter_by(
                company_id=cid, owner_id=satis_user.id,
            ).count()
            if existing_ref_count == 0:
                # ABC Tekstil müşterisini bul
                abc = db.query(Customer).filter_by(company_id=cid).filter(
                    Customer.name.like("ABC%")
                ).first()
                customer_id = abc.id if abc else None
                ref1 = Reference(
                    company_id=cid,
                    ref_no=generate_ref_no(db, "toplanti", "ABC", date(2026, 6, 1)),
                    customer_id=customer_id,
                    title="ABC Tekstil — Bahar Toplantısı 2026",
                    event_type="toplanti",
                    check_in=date(2026, 6, 1), check_out=date(2026, 6, 3),
                    status="aktif",
                    created_by=satis_user.id,
                    owner_id=satis_user.id,
                )
                db.add(ref1)
                ref2 = Reference(
                    company_id=cid,
                    ref_no=generate_ref_no(db, "konferans", "ABC", date(2026, 9, 15)),
                    customer_id=customer_id,
                    title="ABC Tekstil — Sektör Konferansı",
                    event_type="konferans",
                    check_in=date(2026, 9, 15), check_out=date(2026, 9, 17),
                    status="aktif",
                    created_by=satis_user.id,
                    owner_id=satis_user.id,
                )
                db.add(ref2)
                db.commit()
                print("[seed-rbac] Satış user için 2 test referansı oluşturuldu.")

        # E-Fatura modül flag'ini test için aktif et (muhasebe sidebar'da göstersin)
        from models import SystemSetting
        for module_key in ("einvoice", "edefter", "tax_reports", "bordro"):
            flag_key = f"module_{module_key}_enabled"
            existing = db.query(SystemSetting).filter_by(key=flag_key).first()
            if not existing:
                db.add(SystemSetting(key=flag_key, value="1"))
            elif existing.value != "1":
                existing.value = "1"
        db.commit()

        print("[seed-rbac] RBAC v2 test verileri hazır.")
    except Exception as exc:
        db.rollback()
        print(f"[seed-rbac] HATA: {exc}")
    finally:
        db.close()


def _promote_admin_to_super_admin() -> None:
    """admin@miceapp.net'u super_admin yapar — zaten öyleyse dokunmaz."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email="admin@miceapp.net").first()
        if user and user.role != "super_admin":
            user.role = "super_admin"
            db.commit()
            print("[seed] admin@miceapp.net → super_admin yapıldı.")
    except Exception:
        db.rollback()
    finally:
        db.close()


def _seed_payroll_settings() -> None:
    """2026 bordro sabitlerini oluştur — zaten varsa dokunma."""
    with SessionLocal() as db:
        if db.query(PayrollSettings).filter_by(year=2026).first():
            return
        db.add(PayrollSettings(
            year=2026,
            sgk_employee_rate=0.14,
            sgk_employer_rate=0.2175,
            unemployment_emp_rate=0.01,
            unemployment_empl_rate=0.02,
            sgdp_employee_rate=0.075,
            sgdp_employer_rate=0.225,
            stamp_tax_rate=0.00759,
            gv_istisnasi=4211.33,
            dv_istisnasi=250.70,
            kidem_tavan=49329.0,
            weekly_hours=45,
            asgari_ucret_brut=26005.50,
        ))
        db.commit()
        print("[db] PayrollSettings 2026 seed eklendi.")


_DEFAULT_VENDOR_TYPES = [
    ("genel",    "Genel Tedarikçi", 1),
    ("otel",     "Otel",            2),
    ("etkinlik", "Etkinlik Mekanı", 3),
    ("teknik",   "Teknik Ekipman",  4),
    ("transfer", "Transfer",        5),
    ("catering", "Catering",        6),
    ("tasarim",  "Tasarım & Baskı", 7),
    ("diger",    "Diğer",           99),
]


def _seed_vendor_types() -> None:
    db = SessionLocal()
    try:
        changed = False
        for value, label, sort_order in _DEFAULT_VENDOR_TYPES:
            if not db.query(VendorType).filter_by(value=value).first():
                db.add(VendorType(value=value, label=label, sort_order=sort_order))
                changed = True
        if changed:
            db.commit()
            print("[seed] Tedarikçi tipleri eklendi.")
    finally:
        db.close()


def _fix_stale_logo_paths() -> None:
    """DB'deki eski dosya yolu logo değerlerini temizle (data: URI veya http değilse sil)."""
    db = SessionLocal()
    try:
        from models import SystemSetting, Company
        from templates_config import invalidate_company_cache

        # SystemSetting temizle
        for key in ("company_logo_path", "company_logo_dark_path"):
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row and row.value and not (row.value.startswith("data:") or row.value.startswith("http")):
                print(f"[db] Stale logo temizlendi (SystemSetting): {key}")
                row.value = ""

        # Company tablosundaki eski dosya yollarını da temizle
        for co in db.query(Company).all():
            if co.logo_path and not (co.logo_path.startswith("data:") or co.logo_path.startswith("http")):
                print(f"[db] Stale logo temizlendi (Company id={co.id}): logo_path")
                co.logo_path = None

        db.commit()
        invalidate_company_cache()
    except Exception as exc:
        print(f"[db] _fix_stale_logo_paths hata: {exc}")
    finally:
        db.close()


def init_db() -> None:
    if os.environ.get("RESET_DB") == "1":
        print("[db] RESET_DB=1 — şema sıfırlanıyor...")
        if not DATABASE_URL.startswith("sqlite"):
            from sqlalchemy import text as _text
            with engine.connect() as _conn:
                _conn.execute(_text("DROP SCHEMA public CASCADE"))
                _conn.execute(_text("CREATE SCHEMA public"))
                _conn.execute(_text("GRANT ALL ON SCHEMA public TO postgres"))
                _conn.execute(_text("GRANT ALL ON SCHEMA public TO public"))
                _conn.commit()
        else:
            Base.metadata.drop_all(bind=engine)
        print("[db] Şema sıfırlandı.")
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as _e:
        print(f"[db] create_all uyarı (tek tek denenecek): {_e}")
        for _tbl in Base.metadata.sorted_tables:
            try:
                _tbl.create(bind=engine, checkfirst=True)
            except Exception as _te:
                print(f"[db] {_tbl.name} oluşturulamadı (atlandı): {_te}")
    _migrate(engine)
    print("[db] Tablolar hazır.")
    seed_data()
    _seed_extra_categories()
    _seed_leave_types()
    _fix_kurban_2026()
    _seed_public_holidays_2026()
    _seed_payroll_settings()
    _seed_vendor_types()
    _seed_default_company()
    _seed_demo_company()
    _seed_departments_and_access()
    _seed_approval_limits()
    _seed_rbac_test_users()
    _promote_admin_to_super_admin()
    _fix_stale_logo_paths()


if __name__ == "__main__":
    init_db()
