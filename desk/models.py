"""
Satın Alma — Ön Muhasebe Sistemi
SQLAlchemy modelleri
"""

from __future__ import annotations

import uuid as _uuid_mod
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

def _uuid() -> str:
    return str(_uuid_mod.uuid4())

def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Şirket (multi-tenancy kökü)
# ---------------------------------------------------------------------------

class Company(Base):
    __tablename__ = "companies"

    id         = Column(String(36), primary_key=True, default=_uuid)
    name       = Column(String(200), nullable=False)
    short_name = Column(String(80))
    tax_no     = Column(String(20))
    tax_office = Column(String(100))
    address    = Column(String(300))
    phone      = Column(String(40))
    email      = Column(String(200))
    logo_path  = Column(Text)
    active     = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Referans kapanış onay limitleri (NULL = kendi başına kapatamaz)
    ref_close_limit_kullanici = Column(Float, nullable=True)
    ref_close_limit_mudur     = Column(Float, nullable=True)
    # Demo şirket bayrağı
    is_demo       = Column(Boolean, default=False, nullable=False, server_default="false")
    demo_reset_at = Column(DateTime, nullable=True)
    # --- SaaS / multi-tenant alanları (miceapp suite — company = tenant) ---
    slug          = Column(String(100), unique=True, index=True, nullable=True)   # subdomain / URL slug
    plan          = Column(String(20), default="starter", nullable=False, server_default="starter")
    trial_ends_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLE_ORDER = ["kullanici", "mudur", "genel_mudur", "admin", "super_admin"]

ROLE_LABELS = {
    "kullanici":   "Kullanıcı",
    "mudur":       "Müdür",
    "genel_mudur": "Genel Müdür",
    "admin":       "Admin",
    "super_admin": "Süper Admin",
}


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(120), nullable=False)
    surname = Column(String(120), nullable=True)
    title = Column(String(150), nullable=True)
    phone = Column(String(40), nullable=True)
    email = Column(String(200), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="kullanici", nullable=False)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    manager_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    team_id    = Column(String(36), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", foreign_keys=[company_id])
    manager = relationship("User", remote_side="User.id", foreign_keys=[manager_id])

    @hybrid_property
    def is_admin(self) -> bool:
        return self.role in ("admin", "super_admin")

    @is_admin.expression
    def is_admin(cls):
        return cls.role.in_(("admin", "super_admin"))

    @is_admin.setter
    def is_admin(self, value: bool):
        if value and self.role not in ("admin", "super_admin"):
            self.role = "admin"
        elif not value and self.role in ("admin", "super_admin"):
            self.role = "kullanici"

    @hybrid_property
    def is_approver(self) -> bool:
        return self.role in ("genel_mudur", "admin", "super_admin")

    @is_approver.expression
    def is_approver(cls):
        return cls.role.in_(("genel_mudur", "admin", "super_admin"))

    @is_approver.setter
    def is_approver(self, value: bool):
        if value and self.role not in ("genel_mudur", "admin", "super_admin"):
            self.role = "genel_mudur"
        elif not value and self.role == "genel_mudur":
            self.role = "kullanici"

    def has_role_min(self, min_role: str) -> bool:
        """Kullanıcının rolü min_role veya daha yüksek mi?"""
        try:
            return ROLE_ORDER.index(self.role) >= ROLE_ORDER.index(min_role)
        except ValueError:
            return False

    # ---- Departman üyelikleri (RBAC v2) ----
    departments = relationship(
        "Department",
        secondary="user_departments",
        back_populates="users",
        lazy="selectin",
    )

    @property
    def department_keys(self) -> set[str]:
        return {d.key for d in (self.departments or []) if d.active}

    def has_department_key(self, key: str) -> bool:
        return key in self.department_keys

    @property
    def is_super_admin(self) -> bool:
        return self.role == "super_admin"


class RolePermission(Base):
    """Rol-izin matrisi — DB'de override edilmiş izinler burada tutulur.
    Kaydı olmayan izinler DEFAULT_PERMISSIONS'a göre değerlendirilir."""
    __tablename__ = "role_permissions"

    id = Column(String(36), primary_key=True, default=_uuid)
    role = Column(String(30), nullable=False)
    permission = Column(String(60), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("role", "permission"),)


# ---------------------------------------------------------------------------
# Departman & Modül erişimi (RBAC v2)
# ---------------------------------------------------------------------------

class Department(Base):
    """Şirket içi departman (Satış, Muhasebe, İK, Operasyon vb.).
    Her şirket kendi departmanlarını yönetir; küçük şirket Muhasebe+İK'yı
    tek depo'da birleştirebilir."""
    __tablename__ = "departments"

    id         = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    key        = Column(String(40), nullable=False)            # slug: sales, accounting, hr, operations
    name       = Column(String(80), nullable=False)            # "Satış", "Muhasebe & İK", vb.
    color      = Column(String(7),  default="#1A3A5C", nullable=False)
    icon       = Column(String(40), default="bi-people", nullable=False)
    active     = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_department_company_key"),)

    company = relationship("Company", foreign_keys=[company_id])
    users   = relationship("User", secondary="user_departments", back_populates="departments")
    module_access = relationship("ModuleAccess", back_populates="department", cascade="all, delete-orphan")


class UserDepartment(Base):
    """User ↔ Department ara tablosu (N-to-N).
    is_head: bu departmanın müdürü (UI rozeti + departman raporları için)."""
    __tablename__ = "user_departments"

    user_id       = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    department_id = Column(String(36), ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True)
    is_head       = Column(Boolean, default=False, nullable=False)
    assigned_at   = Column(DateTime, default=datetime.utcnow, nullable=False)


class ModuleAccess(Base):
    """Departman → Modül izin matrisi (screen-level).
    Bir departmanın hangi sayfayı görüp düzenleyebileceği."""
    __tablename__ = "module_access"

    id            = Column(String(36), primary_key=True, default=_uuid)
    department_id = Column(String(36), ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    module_key    = Column(String(40), nullable=False)
    can_view      = Column(Boolean, default=True, nullable=False)
    can_edit      = Column(Boolean, default=False, nullable=False)

    __table_args__ = (UniqueConstraint("department_id", "module_key", name="uq_moduleaccess_dept_module"),)

    department = relationship("Department", back_populates="module_access")


# ---------------------------------------------------------------------------
# Takım (event app ile aynı 'teams' tablosunu paylaşır)
# ---------------------------------------------------------------------------

class Team(Base):
    """Etkinlik / operasyon takımı — event app ile ortak tablo."""
    __tablename__ = "teams"

    id              = Column(String(36), primary_key=True, default=_uuid)
    name            = Column(String(200), nullable=False)
    code            = Column(String(50), default="")
    description     = Column(Text, default="")
    active          = Column(Boolean, default=True, nullable=False)
    is_support_team = Column(Boolean, default=False, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)

    @property
    def active_members(self):
        return []


class OrgTitle(Base):
    """Organizasyon unvanları — event app ile ortak 'org_titles' tablosu."""
    __tablename__ = "org_titles"

    id                  = Column(String(36), primary_key=True, default=_uuid)
    name                = Column(String(150), nullable=False)
    grade               = Column(Integer, nullable=False, default=1)
    parent_id           = Column(String(36), ForeignKey("org_titles.id"), nullable=True)
    budget_limit        = Column(Float, nullable=True)
    sort_order          = Column(Integer, default=0)
    pm_permission_level = Column(String(16), nullable=True)

    parent = relationship("OrgTitle", remote_side="OrgTitle.id", foreign_keys=[parent_id])


# ---------------------------------------------------------------------------
# Müşteri & Tedarikçi
# ---------------------------------------------------------------------------

class Customer(Base):
    __tablename__ = "customers"

    id           = Column(String(36), primary_key=True, default=_uuid)
    company_id   = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    owner_id     = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name         = Column(String(200), nullable=False)
    code         = Column(String(10), nullable=False)
    sector       = Column(String(100))
    tax_no       = Column(String(30))
    tax_office   = Column(String(100))
    address      = Column(Text)
    email        = Column(String(200))
    phone        = Column(String(50))
    notes        = Column(Text)
    contacts_json = Column(Text, default="[]")
    payment_term  = Column(String(100), nullable=True)
    payment_dow   = Column(Integer, nullable=True)
    docs_json     = Column(Text, default="[]")
    team_id       = Column(String(36), nullable=True)
    excel_template_path = Column(String(500), default="")
    excel_template_b64  = Column(Text, default="")
    excel_config_json   = Column(Text, default="{}")
    active        = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_efatura_user  = Column(Boolean, nullable=True)
    efatura_alias    = Column(String(100), nullable=True)
    efatura_checked_at = Column(DateTime, nullable=True)

    owner       = relationship("User", foreign_keys=[owner_id])
    references  = relationship("Reference", back_populates="customer")
    cheques     = relationship("Cheque", back_populates="customer")
    prepayments = relationship("CustomerPrepayment", back_populates="customer", order_by="CustomerPrepayment.payment_date.desc()")


class VendorType(Base):
    __tablename__ = "vendor_types"

    id         = Column(String(36), primary_key=True, default=_uuid)
    value      = Column(String(50), nullable=False, unique=True)
    label      = Column(String(100), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    active     = Column(Boolean, default=True, nullable=False)


class Vendor(Base):
    __tablename__ = "vendors"

    id           = Column(String(36), primary_key=True, default=_uuid)
    company_id   = Column(String(36), nullable=True, index=True)  # FK değil — paylaşımlı DB uyumu
    name         = Column(String(255), nullable=False, index=True)
    active       = Column(Boolean, default=True, nullable=False)
    supplier_type = Column(String(50), default="diger")
    city         = Column(String(100), default="")
    cities_json  = Column(Text, default="[]")
    location_type = Column(String(20), default="turkiye")
    address      = Column(Text, default="")
    phone        = Column(String(50), default="")
    email        = Column(String(255), default="")
    contact      = Column(String(200), default="")
    contacts_json = Column(Text, default="[]")
    website      = Column(String(255), default="")
    stars        = Column(Integer, nullable=True)
    total_rooms  = Column(Integer, default=0)
    halls_json   = Column(Text, default="[]")
    docs_json    = Column(Text, default="[]")
    tax_no       = Column(String(30), default="")
    tax_office   = Column(String(100), default="")
    iban         = Column(String(40), default="")
    bank_accounts_json = Column(Text, nullable=True)
    payment_term = Column(Integer, default=30)
    is_efatura_user  = Column(Boolean, nullable=True)
    efatura_alias    = Column(String(100), nullable=True)
    efatura_checked_at = Column(DateTime, nullable=True)
    notes        = Column(Text, default="")
    created_by   = Column(String(36), nullable=True)  # FK değil — paylaşımlı DB uyumu
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    invoices        = relationship("Invoice", back_populates="vendor")
    cheques         = relationship("Cheque", back_populates="vendor")
    general_expenses = relationship("GeneralExpense", back_populates="vendor")
    prepayments     = relationship("VendorPrepayment", back_populates="vendor",
                                   cascade="all, delete-orphan",
                                   order_by="VendorPrepayment.payment_date")


# Backward-compat alias so old import paths still work during transition
FinancialVendor = Vendor


# ---------------------------------------------------------------------------
# Kasa & Banka & Kredi Kartı
# ---------------------------------------------------------------------------

class CashBook(Base):
    __tablename__ = "cash_books"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    entries = relationship("CashEntry", back_populates="book", cascade="all, delete-orphan")
    day_closes = relationship("CashDayClose", back_populates="book", cascade="all, delete-orphan")


class CashDayClose(Base):
    """Gün sonu kapanış kaydı — kapalı günlere artık işlem yapılamaz."""
    __tablename__ = "cash_day_closes"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=False)
    close_date = Column(Date, nullable=False)
    opening_balance = Column(Float, nullable=False, default=0.0)
    closing_balance = Column(Float, nullable=False)
    physical_count = Column(Float, nullable=False)
    difference = Column(Float, nullable=False, default=0.0)
    notes = Column(String(300), nullable=True)
    closed_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    closed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    book = relationship("CashBook", back_populates="day_closes")
    closer = relationship("User", foreign_keys=[closed_by])


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    bank_name = Column(String(100))
    iban = Column(String(40))
    currency = Column(String(3), default="TRY", nullable=False)
    opening_balance = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    movements = relationship("BankMovement", back_populates="account", cascade="all, delete-orphan")
    salary_payments = relationship("SalaryPayment", back_populates="bank_account")
    employee_advances = relationship("EmployeeAdvance", back_populates="bank_account")


class CreditCard(Base):
    __tablename__ = "credit_cards"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    bank_name = Column(String(100))
    last4 = Column(String(4))
    credit_limit = Column(Float, default=0.0, nullable=False)
    statement_day = Column(Integer, nullable=False)
    payment_offset_days = Column(Integer, default=10, nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    txns = relationship("CreditCardTxn", back_populates="card", cascade="all, delete-orphan")
    statements = relationship("CreditCardStatement", back_populates="card", cascade="all, delete-orphan")


class CreditCardStatement(Base):
    __tablename__ = "credit_card_statements"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    card_id = Column(String(36), ForeignKey("credit_cards.id"), nullable=False)
    statement_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Float, default=0.0, nullable=False)
    status = Column(Enum("unpaid", "paid", name="cc_statement_status"), default="unpaid", nullable=False)
    paid_at = Column(DateTime)
    # GM haftalık ödeme listesi kararı
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)

    card = relationship("CreditCard", back_populates="statements")
    txns = relationship("CreditCardTxn", back_populates="statement")


class CreditCardTxn(Base):
    __tablename__ = "credit_card_txns"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    card_id = Column(String(36), ForeignKey("credit_cards.id"), nullable=False)
    statement_id = Column(String(36), ForeignKey("credit_card_statements.id"), nullable=True)
    txn_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(300))
    is_refund = Column(Boolean, default=False, nullable=False)
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=True)
    instruction_id = Column(String(36), ForeignKey("payment_instructions.id"), nullable=True)
    expense_report_id = Column(String(36), nullable=True)  # HBF kredi kartı kalemi bağı (limit düşüşü)

    card = relationship("CreditCard", back_populates="txns")
    statement = relationship("CreditCardStatement", back_populates="txns")


# ---------------------------------------------------------------------------
# Çek
# ---------------------------------------------------------------------------

class Cheque(Base):
    __tablename__ = "cheques"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=True)
    cheque_type = Column(Enum("verilen", "alinan", name="cheque_type_enum"), nullable=False)
    cheque_no = Column(String(50))
    bank = Column(String(100))
    branch = Column(String(100))
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    cheque_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(
        Enum("beklemede", "tahsil_edildi", "iade", "karsilıksız", "iptal", name="cheque_status_enum"),
        default="beklemede", nullable=False
    )
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Tahsilat / ödeme bilgisi
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    settled_date = Column(Date, nullable=True)
    settled_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    attachment = Column(String(300), nullable=True)  # static/cheque_docs/{filename}
    # GM haftalık ödeme listesi kararı
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)
    created_by_instruction_id = Column(String(36), ForeignKey("payment_instructions.id"), nullable=True)

    vendor = relationship("Vendor", back_populates="cheques")
    customer = relationship("Customer", back_populates="cheques")
    bank_account = relationship("BankAccount", foreign_keys=[bank_account_id])
    settler = relationship("User", foreign_keys=[settled_by])


# ---------------------------------------------------------------------------
# Referans (İş / Proje)
# ---------------------------------------------------------------------------

class Reference(Base):
    __tablename__ = "references"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    ref_no = Column(String(40), nullable=False, unique=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=True)
    title = Column(String(300), nullable=False)
    event_type = Column(String(50))
    check_in = Column(Date)
    check_out = Column(Date)
    status = Column(
        Enum("aktif", "tamamlandi", "iptal", "arsiv", name="reference_status_enum"),
        default="aktif", nullable=False
    )
    notes = Column(Text)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    owner_id   = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)  # RBAC v2: proje sahibi
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Kapanış onay akışı
    approval_status = Column(String(30), nullable=True)  # kapanış_talep | mudur_onayladi | gm_onayladi | reddedildi | reaktivasyon_talep
    approval_requested_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approval_requested_at = Column(DateTime, nullable=True)
    mudur_approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    mudur_approved_at = Column(DateTime, nullable=True)
    gm_approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_approved_at = Column(DateTime, nullable=True)
    approval_rejection_note = Column(Text, nullable=True)
    reactivation_requested_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    reactivation_requested_at = Column(DateTime, nullable=True)
    reactivation_note = Column(Text, nullable=True)

    @property
    def is_locked(self) -> bool:
        """GM onayladıktan sonra veya tamamlandi statüsünde kilitli — sadece admin değiştirebilir."""
        return self.approval_status == "gm_onayladi" or self.status == "tamamlandi"

    customer = relationship("Customer", back_populates="references")
    creator = relationship("User", foreign_keys=[created_by])
    owner   = relationship("User", foreign_keys=[owner_id])
    approval_requester = relationship("User", foreign_keys=[approval_requested_by])
    mudur_approver = relationship("User", foreign_keys=[mudur_approved_by])
    gm_approver = relationship("User", foreign_keys=[gm_approved_by])
    reactivation_requester = relationship("User", foreign_keys=[reactivation_requested_by])
    invoices = relationship("Invoice", back_populates="reference")
    cash_entries = relationship("CashEntry", back_populates="reference")
    bank_movements = relationship("BankMovement", back_populates="reference")
    general_expenses = relationship("GeneralExpense", back_populates="reference")


# ---------------------------------------------------------------------------
# Fatura
# ---------------------------------------------------------------------------

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)   # muhasebe bağı (references)
    request_id = Column(String(36), nullable=True, index=True)                # satış bağı (event requests) — FK yok (paylaşımlı DB)
    source_invoice_id = Column(String(36), nullable=True, index=True)         # komisyon: refere ettiği ana tedarikçi (gelen) faturası
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=True)
    invoice_type = Column(
        Enum("gelen", "kesilen", "komisyon", "iade_gelen", "iade_kesilen", name="invoice_type_enum"),
        nullable=False
    )
    invoice_no = Column(String(100))
    invoice_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0.20, nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    # miceapp suite — birleşik status sözlüğü (desk+event): draft|pending|approved|rejected|partial|paid|cancelled
    # ENUM→VARCHAR (iki uygulamanın farklı status değerleri için)
    status = Column(String(20), default="approved", nullable=False)
    # --- miceapp suite: event (miceapp) uyumu için denormalize/kolaylık kolonları ---
    vendor_name   = Column(String(255), default="")
    description   = Column(Text, default="")
    vat_amount    = Column(Float, default=0.0)
    document_path = Column(String(500), nullable=True)
    document_name = Column(String(255), nullable=True)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", "cek", "acik_hesap", name="invoice_payment_method_enum"),
        nullable=True
    )
    paid_at = Column(DateTime)
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    credit_card_id = Column(String(36), ForeignKey("credit_cards.id"), nullable=True)
    cash_book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=True)
    cheque_id = Column(String(36), ForeignKey("cheques.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    items_json = Column(Text, nullable=True)
    notes = Column(Text)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # E-Fatura entegrasyonu (prizma-einvoice paketi tarafından kullanılır)
    einvoice_status = Column(String(20), nullable=True)
    einvoice_uuid = Column(String(64), nullable=True)
    einvoice_pdf_url = Column(Text, nullable=True)
    einvoice_sent_at = Column(DateTime, nullable=True)
    einvoice_inbox_id = Column(Integer, nullable=True)        # gelen invoice ise
    einvoice_external_uuid = Column(String(64), nullable=True)
    # GM (Genel Müdür) haftalık ödeme listesi kararı
    gm_decision = Column(String(20), nullable=True)  # approved | rejected | postponed | NULL
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)  # nakit|banka|kredi_karti|cek|acik_hesap
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)  # kısmi onay için: bu kadar onaylandı, kalan ertelendi
    preparer_note = Column(Text, nullable=True)  # listeyi hazırlayan kullanıcının GM'e yönelik notu

    customer_id     = Column(String(36), ForeignKey("customers.id"), nullable=True)
    attachment_path = Column(String, nullable=True)
    collection_date = Column(Date, nullable=True)
    deleted_at      = Column(DateTime, nullable=True)
    deleted_by      = Column(String(36), ForeignKey("users.id"), nullable=True)
    # Çok kademeli onay akışı (RBAC v2) — fatura, muhasebe girdikten sonra
    # temsilci → müdür → GM zincirinden geçer (limit dahilinde her kademe geçişli).
    approval_status      = Column(String(30), nullable=True)  # onay_bekliyor | approved | reddedildi (NULL=eski kayıtlar)
    current_approver_id  = Column(String(36), ForeignKey("users.id"), nullable=True)
    approval_history     = Column(Text, nullable=True)   # JSON: [{user_id, action, amount, ts, note}]
    approval_rejection_note = Column(Text, nullable=True)
    # Ortak havuz (referanssız gelen faturalar — satış ekibi sahiplenene kadar burada bekler)
    in_pool = Column(Boolean, default=False, server_default="false", nullable=False)
    # Fatura bölme
    is_split_parent = Column(Boolean, default=False, server_default="false", nullable=False)
    split_parent_id = Column(String(36), ForeignKey("invoices.id"), nullable=True)
    # Koordinatör onay akışı (miceapp ↔ micedesk köprüsü)
    coordinator_status    = Column(String(20), nullable=True)   # beklemede | onaylandi | reddedildi
    coordinator_note      = Column(Text, nullable=True)
    coordinator_reviewed_at = Column(DateTime, nullable=True)
    coordinator_reviewed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    # miceapp paylaşımlı kolonlar
    total_amount   = Column(Float, default=0.0, nullable=True)
    payment_status = Column(String(20), default="unpaid", nullable=True)  # unpaid|paid|partial

    reference = relationship("Reference", back_populates="invoices")
    vendor = relationship("Vendor", back_populates="invoices")
    customer = relationship("Customer", foreign_keys=[customer_id])
    creator = relationship("User", foreign_keys=[created_by])
    current_approver = relationship("User", foreign_keys=[current_approver_id])
    bank_account = relationship("BankAccount")
    credit_card = relationship("CreditCard")
    cash_book = relationship("CashBook")
    cheque = relationship("Cheque")
    cash_entries = relationship("CashEntry", back_populates="invoice")
    bank_movements = relationship("BankMovement", back_populates="invoice")
    payments = relationship("InvoicePayment", back_populates="invoice",
                            cascade="all, delete-orphan", order_by="InvoicePayment.payment_date")

    @property
    def total_with_vat(self) -> float:
        return round(self.amount * (1 + self.vat_rate), 2)

    @property
    def paid_amount(self) -> float:
        return round(sum(p.amount for p in self.payments), 2)

    @property
    def remaining(self) -> float:
        return round(self.total_with_vat - self.paid_amount, 2)

    @property
    def remaining_net(self) -> float:
        """KDV hariç kalan tutar — ödenmiş oran net tutara uygulanır."""
        twv = self.total_with_vat
        if twv == 0:
            return 0.0
        paid_frac = min(self.paid_amount / twv, 1.0)
        return round(self.amount * (1 - paid_frac), 2)


# ---------------------------------------------------------------------------
# Kasa Hareketi & Banka Hareketi
# ---------------------------------------------------------------------------

class CashEntry(Base):
    __tablename__ = "cash_entries"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=False)
    entry_date = Column(Date, nullable=False)
    entry_type = Column(Enum("giris", "cikis", name="cash_entry_type_enum"), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(300))
    category = Column(String(100), nullable=True)
    related_party = Column(String(150), nullable=True)
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=True)
    instruction_id = Column(String(36), ForeignKey("payment_instructions.id"), nullable=True)

    book = relationship("CashBook", back_populates="entries")
    reference = relationship("Reference", back_populates="cash_entries")
    invoice = relationship("Invoice", back_populates="cash_entries")


class BankMovement(Base):
    __tablename__ = "bank_movements"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False)
    movement_date = Column(Date, nullable=False)
    movement_type = Column(Enum("giris", "cikis", name="bank_movement_type_enum"), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(300))
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=True)
    instruction_id = Column(String(36), ForeignKey("payment_instructions.id"), nullable=True)

    account = relationship("BankAccount", back_populates="movements")
    reference = relationship("Reference", back_populates="bank_movements")
    invoice = relationship("Invoice", back_populates="bank_movements")


class InvoicePayment(Base):
    """Faturaya bağlı kısmi veya tam ödeme taksiti."""
    __tablename__ = "invoice_payments"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=False)
    payment_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", "cek", name="inv_pmt_method_enum"),
        nullable=False
    )
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    cash_book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=True)
    credit_card_id = Column(String(36), ForeignKey("credit_cards.id"), nullable=True)
    cheque_id = Column(String(36), ForeignKey("cheques.id"), nullable=True)
    notes = Column(String(300))
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    instruction_id = Column(String(36), ForeignKey("payment_instructions.id"), nullable=True)

    invoice = relationship("Invoice", back_populates="payments")
    bank_account = relationship("BankAccount")
    cash_book = relationship("CashBook")
    credit_card = relationship("CreditCard")
    cheque = relationship("Cheque")


class VendorPrepayment(Base):
    """Tedarikçiye fatura kesilmeden yapılan ön/avans ya da doğrudan ödeme."""
    __tablename__ = "vendor_prepayments"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=False)
    payment_type = Column(String(20), default="prepayment", nullable=False)  # prepayment | direct
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    payment_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", "cek", name="vp_method_enum"),
        nullable=False
    )
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    cash_book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=True)
    credit_card_id = Column(String(36), ForeignKey("credit_cards.id"), nullable=True)
    cheque_id = Column(String(36), ForeignKey("cheques.id"), nullable=True)
    notes = Column(String(300))
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    vendor = relationship("Vendor", back_populates="prepayments")
    reference = relationship("Reference")
    bank_account = relationship("BankAccount")
    cash_book = relationship("CashBook")
    credit_card = relationship("CreditCard")
    cheque = relationship("Cheque")


class CustomerPrepayment(Base):
    """Müşteriden fatura kesilmeden önce alınan ön tahsilat veya doğrudan tahsilat."""
    __tablename__ = "customer_prepayments"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False)
    payment_type = Column(String(20), default="prepayment", nullable=False)  # prepayment | direct
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    payment_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(20), nullable=False)  # nakit | banka | cek
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    cash_book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=True)
    cheque_id = Column(String(36), ForeignKey("cheques.id"), nullable=True)
    notes = Column(String(300))
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="prepayments")
    reference = relationship("Reference")
    bank_account = relationship("BankAccount")
    cash_book = relationship("CashBook")
    cheque = relationship("Cheque")


# ---------------------------------------------------------------------------
# Genel Giderler
# ---------------------------------------------------------------------------

class GeneralExpenseCategory(Base):
    __tablename__ = "general_expense_categories"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(String(36), ForeignKey("general_expense_categories.id"), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)

    parent = relationship("GeneralExpenseCategory", remote_side=[id], back_populates="children")
    children = relationship("GeneralExpenseCategory", back_populates="parent")
    expenses = relationship("GeneralExpense", back_populates="category")


class GeneralExpense(Base):
    __tablename__ = "general_expenses"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    category_id = Column(String(36), ForeignKey("general_expense_categories.id"), nullable=False)
    expense_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0.0, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", name="expense_payment_method_enum"),
        nullable=True
    )
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=True)
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=True)
    source = Column(
        Enum("manual", "salary", "benefit", "advance", name="expense_source_enum"),
        default="manual", nullable=False
    )
    description = Column(String(300))
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    category = relationship("GeneralExpenseCategory", back_populates="expenses")
    vendor = relationship("Vendor", back_populates="general_expenses")
    reference = relationship("Reference", back_populates="general_expenses")
    employee = relationship("Employee", back_populates="general_expenses")
    creator = relationship("User")


# ---------------------------------------------------------------------------
# Çalışanlar
# ---------------------------------------------------------------------------

class Employee(Base):
    __tablename__ = "employees"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(120), nullable=False)
    title = Column(String(100))
    department = Column(String(100))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    gross_salary = Column(Float, default=0.0, nullable=False)
    net_salary = Column(Float, default=0.0, nullable=False)
    iban = Column(String(40))
    is_retired = Column(Boolean, default=False, nullable=False)  # Emekli çalışan → SGDP
    active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)  # bağlı kullanıcı hesabı

    salary_payments = relationship("SalaryPayment", back_populates="employee", cascade="all, delete-orphan")
    benefits = relationship("EmployeeBenefit", back_populates="employee", cascade="all, delete-orphan")
    advances = relationship("EmployeeAdvance", back_populates="employee", cascade="all, delete-orphan")
    general_expenses = relationship("GeneralExpense", back_populates="employee")
    user = relationship("User", foreign_keys=[user_id])
    leave_balances = relationship("LeaveBalance", back_populates="employee", cascade="all, delete-orphan")
    leave_requests = relationship("LeaveRequest", back_populates="employee", cascade="all, delete-orphan")
    personal_info = relationship("EmployeePersonalInfo", back_populates="employee", uselist=False, cascade="all, delete-orphan")
    assets = relationship("EmployeeAsset", back_populates="employee", cascade="all, delete-orphan")
    documents = relationship("EmployeeDocument", back_populates="employee", cascade="all, delete-orphan")
    career_events = relationship("EmployeeCareerEvent", back_populates="employee", cascade="all, delete-orphan")


class SalaryPayment(Base):
    __tablename__ = "salary_payments"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False)
    period = Column(String(7), nullable=False)  # YYYY-MM
    gross_amount = Column(Float, nullable=False)
    net_amount = Column(Float, nullable=False)
    payment_method = Column(Enum("nakit", "banka", name="salary_payment_method_enum"), nullable=False)
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    paid_at = Column(DateTime, nullable=False)
    general_expense_id = Column(String(36), ForeignKey("general_expenses.id"), nullable=True)
    notes = Column(Text)
    instruction_id = Column(String(36), ForeignKey("payment_instructions.id"), nullable=True)

    employee = relationship("Employee", back_populates="salary_payments")
    bank_account = relationship("BankAccount", back_populates="salary_payments")
    general_expense = relationship("GeneralExpense")


class EmployeeBenefit(Base):
    __tablename__ = "employee_benefits"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False)
    benefit_type = Column(
        Enum("yemek", "ulasim", "saglik", "diger", name="benefit_type_enum"),
        nullable=False
    )
    period = Column(String(7), nullable=False)  # YYYY-MM
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", name="benefit_payment_method_enum"),
        nullable=False
    )
    general_expense_id = Column(String(36), ForeignKey("general_expenses.id"), nullable=True)
    notes = Column(Text)

    employee = relationship("Employee", back_populates="benefits")
    general_expense = relationship("GeneralExpense")


class EmployeeAdvance(Base):
    __tablename__ = "employee_advances"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False)
    amount = Column(Float, nullable=False)
    advance_date = Column(Date, nullable=True)   # ödeme tarihi (onaylanınca set edilir)
    reason = Column(String(300))
    # "maas" = maaş avansı, "is" = iş avansı (referansa bağlı)
    advance_type = Column(String(10), default="maas", nullable=False)
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    # Talep/onay akışı
    approval_status = Column(String(20), default="onaylandi", nullable=False)
    # talep | onaylandi | reddedildi
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_note = Column(String(300), nullable=True)
    # Ödeme
    status = Column(
        Enum("open", "partial", "closed", name="advance_status_enum"),
        default="open", nullable=False
    )
    repaid_amount = Column(Float, default=0.0, nullable=False)
    payment_method = Column(Enum("nakit", "banka", name="advance_payment_method_enum"), nullable=True)
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    # İş avansı kapatma
    expense_items_json = Column(Text)
    cash_return_amount = Column(Float, default=0.0)
    closed_at = Column(Date, nullable=True)
    closed_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    employee = relationship("Employee", back_populates="advances")
    bank_account = relationship("BankAccount", back_populates="employee_advances")
    reference = relationship("Reference")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by_id])


class EmployeePersonalInfo(Base):
    __tablename__ = "employee_personal_info"

    id          = Column(String(36), primary_key=True, default=_uuid)
    company_id  = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False, unique=True)

    tc_kimlik_no    = Column(String(11))
    birth_date      = Column(Date)
    birth_place     = Column(String(100))
    gender          = Column(String(20))   # erkek/kadin/belirtmek_istemiyorum
    marital_status  = Column(String(20))   # bekar/evli/bosanmis/dul
    num_children    = Column(Integer, default=0)
    education_level = Column(String(30))   # ilkokul/ortaokul/lise/onlisans/lisans/yukseklisans/doktora
    military_status = Column(String(30))   # muaf/tamamlandi/ertelendi/tecilli
    blood_type      = Column(String(5))    # A+/A-/B+/B-/AB+/AB-/0+/0-
    disability_degree = Column(Integer, default=0)

    emergency_contact_name     = Column(String(100))
    emergency_contact_phone    = Column(String(20))
    emergency_contact_relation = Column(String(50))

    nationality    = Column(String(50), default="TC")
    address        = Column(Text)
    clothing_size  = Column(String(10))   # XS/S/M/L/XL/XXL/XXXL

    employee = relationship("Employee", back_populates="personal_info")


class EmployeeAsset(Base):
    __tablename__ = "employee_assets"

    id          = Column(String(36), primary_key=True, default=_uuid)
    company_id  = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False)
    asset_type  = Column(String(30), nullable=False)  # laptop/telefon/arac/tablet/yazilim/diger
    brand       = Column(String(100))
    model_name  = Column(String(100))
    serial_no   = Column(String(100))
    zimmet_date = Column(Date, nullable=False)
    return_date = Column(Date)
    status      = Column(String(20), default="zimmetli")  # zimmetli/iade_edildi
    description = Column(Text)
    notes       = Column(Text)
    created_by  = Column(String(36), ForeignKey("users.id"))
    created_at  = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", back_populates="assets")


class EmployeeDocument(Base):
    __tablename__ = "employee_documents"

    id          = Column(String(36), primary_key=True, default=_uuid)
    company_id  = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False)
    doc_type    = Column(String(50))   # sozlesme/kimlik/diploma/sertifika/diger
    title       = Column(String(200), nullable=False)
    file_path   = Column(String(500), nullable=False)
    file_name   = Column(String(200))
    file_size   = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    uploaded_by = Column(String(36), ForeignKey("users.id"))
    notes       = Column(Text)

    employee = relationship("Employee", back_populates="documents")


class EmployeeCareerEvent(Base):
    __tablename__ = "employee_career_events"

    id          = Column(String(36), primary_key=True, default=_uuid)
    company_id  = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False)
    event_date  = Column(Date, nullable=False)
    event_type  = Column(String(30))  # ise_giris/unvan/maas/departman/terfi/ayrilis/diger
    old_value   = Column(String(200))
    new_value   = Column(String(200))
    description = Column(Text)
    created_by  = Column(String(36), ForeignKey("users.id"))
    created_at  = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", back_populates="career_events")


# ---------------------------------------------------------------------------
# Faaliyet Raporu / Yıllık Bütçe
# ---------------------------------------------------------------------------

class AnnualBudget(Base):
    __tablename__ = "annual_budgets"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    year = Column(Integer, nullable=False, unique=True)
    notes = Column(String(300))
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lines = relationship("BudgetLine", back_populates="budget", cascade="all, delete-orphan")


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    budget_id = Column(String(36), ForeignKey("annual_budgets.id"), nullable=False)
    line_type = Column(String(20), nullable=False)  # gelir | gider | maas | sabit
    category_id = Column(String(36), ForeignKey("general_expense_categories.id"), nullable=True)
    label = Column(String(150), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    month_1 = Column(Float, default=0.0, nullable=False)
    month_2 = Column(Float, default=0.0, nullable=False)
    month_3 = Column(Float, default=0.0, nullable=False)
    month_4 = Column(Float, default=0.0, nullable=False)
    month_5 = Column(Float, default=0.0, nullable=False)
    month_6 = Column(Float, default=0.0, nullable=False)
    month_7 = Column(Float, default=0.0, nullable=False)
    month_8 = Column(Float, default=0.0, nullable=False)
    month_9 = Column(Float, default=0.0, nullable=False)
    month_10 = Column(Float, default=0.0, nullable=False)
    month_11 = Column(Float, default=0.0, nullable=False)
    month_12 = Column(Float, default=0.0, nullable=False)

    budget = relationship("AnnualBudget", back_populates="lines")
    category = relationship("GeneralExpenseCategory")


class FixedExpense(Base):
    __tablename__ = "fixed_expenses"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    label = Column(String(150), nullable=False)
    category_id = Column(String(36), ForeignKey("general_expense_categories.id"), nullable=True)
    amount = Column(Float, nullable=False)
    recurrence = Column(String(20), default="monthly", nullable=False)  # monthly | quarterly | yearly | once
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    notes = Column(String(300))
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    category = relationship("GeneralExpenseCategory")


# ---------------------------------------------------------------------------
# HBF — Harcama Bildirim Formu
# ---------------------------------------------------------------------------

class HBF(Base):
    __tablename__ = "hbf_forms"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    hbf_no = Column(String(30), unique=True, nullable=False)
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)   # birincil ref (backward compat)
    refs_json = Column(Text)            # JSON: [{"id":1,"ref_no":"TOP-ABC-2501-001"}]
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=True)
    title = Column(String(200), nullable=True)
    # items_json format: [{date, description, payment, document_type,
    #   amount_with_vat, vat_rate, vat_amount, amount_without_vat}]
    items_json = Column(Text)
    total_amount = Column(Float, default=0.0, nullable=False)   # KDV dahil genel toplam
    status = Column(
        Enum("taslak", "beklemede", "mudur_onayladi", "onaylandi", "reddedildi", "odendi",
             name="hbf_status_enum"),
        default="taslak", nullable=False,
    )
    # İki aşamalı onay
    manager_approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    manager_approved_at = Column(DateTime, nullable=True)
    notes = Column(Text)
    approval_note = Column(Text)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    paid_at = Column(Date, nullable=True)
    payment_method = Column(String(20), nullable=True)
    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    cash_book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=True)
    general_expense_id = Column(String(36), ForeignKey("general_expenses.id"), nullable=True)
    # JSON: [{"filename":"uuid_xxx.pdf","original":"fiş.pdf","uploaded_at":"2026-04-24"}]
    attachments_json = Column(Text)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    reference = relationship("Reference")
    employee = relationship("Employee")
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    bank_account = relationship("BankAccount")
    cash_book = relationship("CashBook")


# ---------------------------------------------------------------------------
# Fon Havuzu
# ---------------------------------------------------------------------------

class FundPool(Base):
    __tablename__ = "fund_pools"

    id             = Column(String(36), primary_key=True, default=_uuid)
    company_id     = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    name           = Column(String(200), nullable=False)
    customer_id    = Column(String(36), ForeignKey("customers.id"), nullable=True)
    currency       = Column(String(3), default="TRY", nullable=False)
    initial_amount = Column(Float, nullable=False)        # KDV dahil başlangıç
    vat_rate       = Column(Float, default=0.20)          # 0.20 = %20
    invoice_date   = Column(Date, nullable=True)
    invoice_no     = Column(String(100), nullable=True)
    year           = Column(Integer, nullable=True)
    notes          = Column(String(500), nullable=True)
    created_by     = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer  = relationship("Customer")
    creator   = relationship("User", foreign_keys=[created_by])
    transfers = relationship(
        "FundTransfer", back_populates="fund_pool",
        cascade="all, delete-orphan",
        order_by="FundTransfer.transfer_date",
    )


class FundTransfer(Base):
    __tablename__ = "fund_transfers"

    id            = Column(String(36), primary_key=True, default=_uuid)
    company_id    = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    fund_pool_id  = Column(String(36), ForeignKey("fund_pools.id"), nullable=False)
    ref_id        = Column(String(36), ForeignKey("references.id"), nullable=True)
    direction     = Column(
        Enum("out", "in", name="fund_direction_enum"), nullable=False
    )
    amount        = Column(Float, nullable=False)          # KDV dahil
    vat_rate      = Column(Float, default=0.20)
    exchange_rate = Column(Float, default=1.0)            # TRY kuru (yabancı para için) = event exchange_rate_try
    currency      = Column(String(3), default="TRY", nullable=False)  # miceapp suite: çoklu para birimi (event'ten)
    transfer_date = Column(Date, nullable=False)
    description   = Column(String(300), nullable=True)
    created_by    = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    fund_pool = relationship("FundPool", back_populates="transfers")
    reference = relationship("Reference")
    creator   = relationship("User", foreign_keys=[created_by])


HBF_STATUS_LABELS = {
    "taslak":          "Taslak",
    "beklemede":       "Beklemede",
    "mudur_onayladi":  "Müdür Onayladı",
    "onaylandi":       "GM Onayladı",
    "reddedildi":      "Reddedildi",
    "odendi":          "Kapandı",
}


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

EVENT_TYPES = [
    ("toplanti", "Toplantı"),
    ("konferans", "Konferans"),
    ("gala", "Gala"),
    ("egitim", "Eğitim"),
    ("lansman", "Lansman"),
    ("diger", "Diğer"),
]

EVENT_TYPE_CODES = {
    "toplanti": "TOP",
    "konferans": "KON",
    "gala": "GAL",
    "egitim": "EGT",
    "lansman": "LAN",
    "diger": "ETK",
}

# Satış ekibi etkinlik tipleri — referans numarası ön eki
SALES_EVENT_TYPES = [
    ("yi", "Yurt İçi"),
    ("yd", "Yurt Dışı"),
    ("tk", "Kongre"),
    ("ut", "Ürün Tanıtım Toplantısı"),
    ("dk", "Danışma Kurulu Toplantısı"),
]

INVOICE_TYPES = [
    ("gelen", "Gelen Fatura"),
    ("kesilen", "Kesilen Fatura"),
    ("komisyon", "Komisyon Faturası"),
    ("iade_gelen", "İade - Gelen"),
    ("iade_kesilen", "İade - Kesilen"),
]

PAYMENT_METHODS = [
    ("nakit", "Nakit"),
    ("banka", "Banka Havalesi"),
    ("kredi_karti", "Kredi Kartı"),
    ("cek", "Çek"),
    ("acik_hesap", "Açık Hesap"),
]

VAT_RATES = [0.0, 0.01, 0.08, 0.10, 0.18, 0.20]


# ---------------------------------------------------------------------------
# Maaş kararı (PayrollDecision) — bir ay için GM toplu maaş kararını saklar
# ---------------------------------------------------------------------------

class PayrollDecision(Base):
    __tablename__ = "payroll_decisions"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    period = Column(String(7), nullable=False, unique=True)  # YYYY-MM
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Notification — kullanıcıya gönderilen bildirimler
# ---------------------------------------------------------------------------

def _now():
    return datetime.utcnow()


class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(String(36), primary_key=True, default=_uuid)
    user_id    = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    notif_type = Column(String(50), nullable=False, default="info")  # info | success | warning | danger
    title      = Column(String(200), nullable=False)
    message    = Column(String(500))
    link       = Column(String(300))
    ref_id     = Column(String(36))   # ilgili kaydın ID'si (UUID — herhangi bir tablo)
    read_at    = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id])


# ---------------------------------------------------------------------------
# ExpenseReport / ExpenseItem — ORTAK HBF (event ile paylaşımlı tablolar)
# Kanonik tablo event'in expense_reports/expense_items'ı; desk buradan okur/yazar.
# Onay zinciri: draft→submitted(müdür)→mudur_onayladi(GM)→onaylandi(muhasebe)→kapandi
# ---------------------------------------------------------------------------

class ExpenseReport(Base):
    __tablename__ = "expense_reports"
    __table_args__ = {"extend_existing": True}

    id                  = Column(String(36), primary_key=True, default=_uuid)
    company_id          = Column(String(36), index=True)
    request_id          = Column(String(36))
    request_ids_json    = Column(Text)
    title               = Column(String(300))
    status              = Column(String(16), default="draft")
    submitted_by        = Column(String(36))
    owner_approved_by   = Column(String(36))
    owner_approved_at   = Column(DateTime)
    manager_approved_by = Column(String(36))
    manager_approved_at = Column(DateTime)
    approved_by         = Column(String(36))
    approved_at         = Column(DateTime)
    rejection_note      = Column(Text)
    paid_by             = Column(String(36))
    paid_at             = Column(DateTime)
    payment_method      = Column(String(20))
    bank_account_id     = Column(String(36))
    cash_book_id        = Column(String(36))
    general_expense_id  = Column(String(36))
    created_at          = Column(DateTime)
    updated_at          = Column(DateTime)

    items = relationship("ExpenseItem", back_populates="report",
                         order_by="ExpenseItem.sort_order")

    @property
    def grand_total(self) -> float:
        return round(sum((i.total_amount or 0) for i in self.items), 2)

    @property
    def grand_excl_vat(self) -> float:
        return round(sum((i.amount or 0) for i in self.items), 2)

    @property
    def grand_vat(self) -> float:
        return round(sum((i.vat_amount or 0) for i in self.items), 2)


class DeskRequest(Base):
    """event'in requests tablosu için bridge. HBF için: ref_no eşleşen request yoksa
    desk'te referanstan minimal bir request oluşturulur (expense_reports FK'sı için)."""
    __tablename__ = "requests"
    __table_args__ = {"extend_existing": True}

    id           = Column(String(36), primary_key=True, default=_uuid)
    request_no   = Column(String(50))
    client_name  = Column(String(200))
    event_name   = Column(String(200))
    status       = Column(String(30))
    is_funded    = Column(Boolean, default=False)
    is_fund_pool = Column(Boolean, default=False)
    created_by   = Column(String(36))
    created_at   = Column(DateTime)
    updated_at   = Column(DateTime)


class EventPrepaymentRequest(Base):
    """event'in prepayment_requests tablosu için bridge — muhasebe (desk) GM onaylı
    ön ödemeleri görür ve öder. event GM onayı kanonik; desk sadece öder/kapatır."""
    __tablename__ = "prepayment_requests"
    __table_args__ = {"extend_existing": True}

    id             = Column(String(36), primary_key=True, default=_uuid)
    company_id     = Column(String(36), index=True)
    vendor_id      = Column(String(36))
    request_id     = Column(String(36))
    amount         = Column(Float)
    needed_date    = Column(String(10))
    description    = Column(Text)
    notes          = Column(Text)
    status         = Column(String(20))   # pending_gm|approved|paid|rejected|cancelled
    requested_by   = Column(String(36))
    approved_at    = Column(DateTime)
    approval_note  = Column(String(500))   # GM'in muhasebeye notu
    paid_by        = Column(String(36))
    paid_at        = Column(String(10))
    payment_method = Column(String(20))
    vendor_prepayment_id = Column(String(36))
    document_path  = Column(String(500))
    document_name  = Column(String(255))
    updated_at     = Column(DateTime)


class ExpenseItem(Base):
    __tablename__ = "expense_items"
    __table_args__ = {"extend_existing": True}

    id                  = Column(String(36), primary_key=True, default=_uuid)
    report_id           = Column(String(36), ForeignKey("expense_reports.id"), index=True)
    assigned_request_id = Column(String(36))
    item_date           = Column(String(10))
    description         = Column(String(300))
    payment_method      = Column(String(16))
    credit_card_id      = Column(String(36))
    document_type       = Column(String(16))
    amount              = Column(Float)
    vat_rate            = Column(Float)
    vat_amount          = Column(Float)
    total_amount        = Column(Float)
    document_path       = Column(String(500))
    document_name       = Column(String(255))
    sort_order          = Column(Integer)
    created_at          = Column(DateTime)

    report = relationship("ExpenseReport", back_populates="items")

    @property
    def payment_label(self) -> str:
        return {"kredi_karti": "Kredi Kartı", "nakit": "Nakit"}.get(self.payment_method, self.payment_method or "")

    @property
    def doc_label(self) -> str:
        return {"fatura": "Fatura", "fis": "Fiş", "belgesiz": "Belgesiz"}.get(self.document_type, self.document_type or "")


# ---------------------------------------------------------------------------
# SystemSetting — basit key-value config (örn. ödeme günü)
# ---------------------------------------------------------------------------

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# ManualPaymentLine — haftalık listeye manuel olarak eklenen ödeme kalemi
# (sistemde fatura/çek/ekstre olarak kayıtlı olmayan ödemeler için)
# ---------------------------------------------------------------------------

class ManualPaymentLine(Base):
    __tablename__ = "manual_payment_lines"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    description = Column(String(300), nullable=False)
    party = Column(String(200))          # serbest metin tedarikçi/karşı taraf
    amount = Column(Float, nullable=False)
    payment_method = Column(String(20), default="banka", nullable=False)
    due_date = Column(Date, nullable=True)
    ref_id = Column(String(36), ForeignKey("references.id"), nullable=True)
    notes = Column(Text)
    status = Column(String(20), default="open", nullable=False)  # open | paid | cancelled
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    # GM ödeme listesi alanları (Invoice/Cheque ile aynı)
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)

    creator = relationship("User", foreign_keys=[created_by])


# ---------------------------------------------------------------------------
# PaymentInstruction — GM onay → operatör infaz arasındaki bekleyen talimat
# ---------------------------------------------------------------------------

class PaymentInstruction(Base):
    __tablename__ = "payment_instructions"

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    # Kaynak: hangi kalem türü için bu talimat
    source_type = Column(String(20), nullable=False)  # invoice|cheque|cc_statement|payroll
    source_id = Column(Integer, nullable=True)        # invoice.id / cheque.id / cc_statement.id
    source_period = Column(String(7), nullable=True)  # payroll için 'YYYY-MM'
    # GM onay verisi
    amount = Column(Float, nullable=False)
    payment_method = Column(String(20), nullable=False)  # nakit|banka|kredi_karti|cek
    note = Column(Text, nullable=True)
    # Operatör infaz hedefi (execution'da seçilir)
    target_bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=True)
    target_cash_book_id = Column(String(36), ForeignKey("cash_books.id"), nullable=True)
    target_credit_card_id = Column(String(36), ForeignKey("credit_cards.id"), nullable=True)
    # Durum
    status = Column(String(20), default="pending", nullable=False)  # pending|executed|cancelled
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)  # GM
    executed_at = Column(DateTime, nullable=True)
    executed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    cancel_reason = Column(Text, nullable=True)

    creator = relationship("User", foreign_keys=[created_by])
    executor = relationship("User", foreign_keys=[executed_by])
    canceller = relationship("User", foreign_keys=[cancelled_by])
    target_bank_account = relationship("BankAccount")
    target_cash_book = relationship("CashBook")
    target_credit_card = relationship("CreditCard")


# ---------------------------------------------------------------------------
# İzin Yönetimi
# ---------------------------------------------------------------------------

class LeaveType(Base):
    """İzin türü tanımları — admin tarafından yönetilir."""
    __tablename__ = "leave_types"

    id               = Column(String(36), primary_key=True, default=_uuid)
    code             = Column(String(40), nullable=False, unique=True)
    name             = Column(String(100), nullable=False)
    is_paid          = Column(Boolean, default=True, nullable=False)
    requires_balance = Column(Boolean, default=True, nullable=False)  # False: bakiyeden düşme
    requires_report  = Column(Boolean, default=False, nullable=False)  # Hastalık: rapor zorunlu
    default_days     = Column(Float, nullable=True)   # Mazeret/dogum_gunu için sabit süre
    color            = Column(String(7), default="#3b82f6", nullable=False)  # takvim rengi
    active           = Column(Boolean, default=True, nullable=False)
    sort_order       = Column(Integer, default=0, nullable=False)

    balances  = relationship("LeaveBalance", back_populates="leave_type")
    requests  = relationship("LeaveRequest", back_populates="leave_type")


class LeaveBalance(Base):
    """Çalışan bazlı yıllık izin bakiyesi — dönem = işe giriş yıl dönümü."""
    __tablename__ = "leave_balances"

    id                = Column(String(36), primary_key=True, default=_uuid)
    company_id        = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id       = Column(String(36), ForeignKey("employees.id"), nullable=False)
    leave_type_id     = Column(String(36), ForeignKey("leave_types.id"), nullable=False)
    period_start      = Column(Date, nullable=False)   # işe giriş yıl dönümü
    period_end        = Column(Date, nullable=False)   # period_start + 1 yıl - 1 gün
    entitled_days     = Column(Float, default=0.0, nullable=False)   # müdürün girdiği hak
    carried_over_days = Column(Float, default=0.0, nullable=False)   # önceki dönemden devir
    notes             = Column(String(300), nullable=True)
    created_by        = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at        = Column(DateTime, default=datetime.utcnow, nullable=False)

    employee   = relationship("Employee", back_populates="leave_balances")
    leave_type = relationship("LeaveType", back_populates="balances")
    creator    = relationship("User", foreign_keys=[created_by])

    __table_args__ = (UniqueConstraint("employee_id", "leave_type_id", "period_start"),)

    @property
    def used_days(self) -> float:
        """Dönem içindeki onaylı izin günleri (relationship üzerinden hesaplanır)."""
        return round(sum(
            r.total_days for r in self.employee.leave_requests
            if r.leave_type_id == self.leave_type_id
            and r.status == "onaylandi"
            and self.period_start <= r.start_date <= self.period_end
        ), 1)

    @property
    def remaining_days(self) -> float:
        return round(self.entitled_days + self.carried_over_days - self.used_days, 1)


class LeaveRequest(Base):
    """İzin talebi."""
    __tablename__ = "leave_requests"

    id            = Column(String(36), primary_key=True, default=_uuid)
    company_id    = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id   = Column(String(36), ForeignKey("employees.id"), nullable=False)
    leave_type_id = Column(String(36), ForeignKey("leave_types.id"), nullable=False)
    start_date    = Column(Date, nullable=False)
    end_date      = Column(Date, nullable=False)
    total_days    = Column(Float, nullable=False)          # hafta sonu + tatil hariç
    half_day      = Column(Boolean, default=False, nullable=False)
    half_day_period = Column(
        Enum("sabah", "ogleden_sonra", name="half_day_period_enum"),
        nullable=True
    )  # sabah=09:00-13:00, ogleden_sonra=13:00-18:00
    has_report    = Column(Boolean, default=False, nullable=False)  # hastalık raporu var mı?
    reason        = Column(Text, nullable=True)
    status        = Column(
        Enum("talep", "mudur_onayladi", "onaylandi", "reddedildi", "iptal",
             name="leave_status_enum"),
        default="talep", nullable=False,
    )
    rejection_note          = Column(Text, nullable=True)
    requested_by            = Column(String(36), ForeignKey("users.id"), nullable=False)
    manager_approved_by     = Column(String(36), ForeignKey("users.id"), nullable=True)
    manager_approved_at     = Column(DateTime, nullable=True)
    final_approved_by       = Column(String(36), ForeignKey("users.id"), nullable=True)
    final_approved_at       = Column(DateTime, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Bordro entegrasyon hazırlığı
    payroll_period          = Column(String(7), nullable=True)   # YYYY-MM
    payroll_processed       = Column(Boolean, default=False, nullable=False)

    employee      = relationship("Employee", back_populates="leave_requests")
    leave_type    = relationship("LeaveType", back_populates="requests")
    requester     = relationship("User", foreign_keys=[requested_by])
    manager_approver = relationship("User", foreign_keys=[manager_approved_by])
    final_approver   = relationship("User", foreign_keys=[final_approved_by])


class PublicHoliday(Base):
    """Resmi tatiller — gün sayısı hesabında hafta içi resmi tatiller çıkarılır."""
    __tablename__ = "public_holidays"

    id      = Column(String(36), primary_key=True, default=_uuid)
    date    = Column(Date, nullable=False, unique=True)
    name    = Column(String(100), nullable=False)
    is_half = Column(Boolean, default=False, nullable=False)  # yarım gün tatil


# ---------------------------------------------------------------------------
# Bordro Modülü
# ---------------------------------------------------------------------------

class PayrollSettings(Base):
    """Yıllık bordro sabitleri — SGK/GV/DV oranları, tavan, asgari ücret."""
    __tablename__ = "payroll_settings"

    id                     = Column(String(36), primary_key=True, default=_uuid)
    company_id             = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    year                   = Column(Integer, nullable=False)
    # Normal çalışan SGK
    sgk_employee_rate      = Column(Float, default=0.14)     # %14
    sgk_employer_rate      = Column(Float, default=0.2175)   # %21,75 (teşvikli)
    unemployment_emp_rate  = Column(Float, default=0.01)     # %1
    unemployment_empl_rate = Column(Float, default=0.02)     # %2
    # Emekli çalışan SGDP
    sgdp_employee_rate     = Column(Float, default=0.075)    # %7,5
    sgdp_employer_rate     = Column(Float, default=0.225)    # %22,5
    # Damga + GV
    stamp_tax_rate         = Column(Float, default=0.00759)
    gv_istisnasi           = Column(Float, default=4211.33)  # Aylık GV istisnası (asgari ücret)
    dv_istisnasi           = Column(Float, default=250.70)   # Aylık DV istisnası
    # Kıdem / diğer
    kidem_tavan            = Column(Float, default=49329.0)  # Yıllık kıdem tazminatı tavanı
    weekly_hours           = Column(Integer, default=45)     # Haftalık normal çalışma saati
    asgari_ucret_brut      = Column(Float, default=26005.50) # 2026 asgari ücret brüt
    updated_at             = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("year", "company_id", name="uq_payroll_settings_year_company"),)


class PayrollRecord(Base):
    """Tek çalışanın tek aya ait bordro kaydı — tüm hesaplama bileşenleri saklanır."""
    __tablename__ = "payroll_records"

    id             = Column(String(36), primary_key=True, default=_uuid)
    company_id     = Column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    employee_id    = Column(String(36), ForeignKey("employees.id"), nullable=False)
    period         = Column(String(7), nullable=False)   # YYYY-MM

    # Girdiler
    gross_salary       = Column(Float, nullable=False)
    overtime_hours     = Column(Float, default=0.0)
    meal_nakit         = Column(Float, default=0.0)   # Nakit yemek yardımı
    meal_ayni          = Column(Float, default=0.0)   # Ayni yemek (SGK istisnası)
    transport          = Column(Float, default=0.0)
    other_additions    = Column(Float, default=0.0)
    unpaid_leave_days  = Column(Float, default=0.0)   # Ücretsiz izin gün sayısı
    paid_leave_days    = Column(Float, default=0.0)   # Ücretli izin gün sayısı (bilgi amaçlı)
    advance_deduction  = Column(Float, default=0.0)   # Avans kesintisi
    # SGK günleri (pusulada gösterim için)
    sgk_gun            = Column(Integer, default=30)  # SGK çalışma günü (max 30)
    fiili_calisma_gun  = Column(Integer, default=0)   # Fiili çalışma günü
    hafta_tatili       = Column(Integer, default=0)   # Hafta sonu günleri
    resmi_tatil_gun    = Column(Integer, default=0)   # Hafta içi resmi tatil
    other_deductions   = Column(Float, default=0.0)
    is_retired_worker  = Column(Boolean, default=False)  # True → SGDP oranları

    # Hesaplanan alanlar
    overtime_pay       = Column(Float, default=0.0)
    normal_earnings    = Column(Float, default=0.0)   # Normal kazanç
    total_gross        = Column(Float, default=0.0)   # Tüm gelirler toplamı
    sgk_base           = Column(Float, default=0.0)   # SGK/SGDP matrahı
    sgk_employee       = Column(Float, default=0.0)   # Çalışan SGK/SGDP
    unemployment_emp   = Column(Float, default=0.0)   # Çalışan işsizlik (emeklide 0)
    sgk_employer       = Column(Float, default=0.0)   # İşveren SGK/SGDP
    unemployment_empl  = Column(Float, default=0.0)   # İşveren işsizlik (emeklide 0)
    gv_base            = Column(Float, default=0.0)   # GV aylık matrahı
    cumulative_gv_base = Column(Float, default=0.0)   # Kümülatif yıllık GV matrahı
    income_tax         = Column(Float, default=0.0)
    stamp_tax_base     = Column(Float, default=0.0)
    stamp_tax          = Column(Float, default=0.0)
    ele_gecen          = Column(Float, default=0.0)   # Ele geçen / net
    employer_cost      = Column(Float, default=0.0)   # İşveren toplam maliyet

    status             = Column(
        Enum("taslak", "onaylandi", "odendi", name="payroll_status_enum"),
        default="taslak", nullable=False
    )
    salary_payment_id  = Column(String(36), ForeignKey("salary_payments.id"), nullable=True)
    notes              = Column(Text)
    created_by         = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow)
    updated_at         = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee")
    __table_args__ = (UniqueConstraint("employee_id", "period", name="uq_payroll_emp_period"),)


LEAVE_STATUS_LABELS = {
    "talep":           ("warning",   "Talep Edildi"),
    "mudur_onayladi":  ("primary",   "Müdür Onayladı"),
    "onaylandi":       ("success",   "Onaylandı"),
    "reddedildi":      ("danger",    "Reddedildi"),
    "iptal":           ("secondary", "İptal"),
}

LEAVE_TYPE_DEFAULTS = [
    # (code, name, is_paid, requires_balance, requires_report, default_days, color, sort_order)
    ("yillik",          "Yıllık İzin",              True,  True,  False, None, "#3b82f6", 1),
    ("hastalik",        "Hastalık İzni",             True,  False, True,  None, "#ef4444", 2),
    ("mazeret_evlilik", "Mazeret İzni — Evlilik",    True,  False, False, 3.0,  "#8b5cf6", 3),
    ("mazeret_olum",    "Mazeret İzni — Ölüm",       True,  False, False, 3.0,  "#6b7280", 4),
    ("mazeret_dogum",   "Mazeret İzni — Doğum",      True,  False, False, 5.0,  "#ec4899", 5),
    ("ucretsiz",        "Ücretsiz İzin",             False, False, False, None, "#f59e0b", 6),
    ("dogum_gunu",      "Doğum Günü İzni",           True,  False, False, 1.0,  "#10b981", 7),
]


# ---------------------------------------------------------------------------
# Satış — Kesilen Fatura Talebi
# ---------------------------------------------------------------------------

class SalesInvoiceRequest(Base):
    """Satış ekibinin muhasebeye kesilen fatura talebi açması için."""
    __tablename__ = "sales_invoice_requests"

    id           = Column(String(36), primary_key=True, default=_uuid)
    # FK constraint yok — mevcut tablolar (references, customers, users) integer PK kullanıyor
    # (tip uyumsuzluğu nedeniyle FK eklenemez; ilişkili objeler router'da manual yüklenir)
    ref_id       = Column(String(36), nullable=True)
    customer_id  = Column(String(36), nullable=False)
    description  = Column(Text, nullable=False)
    amount       = Column(Float, nullable=False)   # KDV hariç
    vat_rate     = Column(Float, default=20.0)
    notes        = Column(Text)
    requested_by = Column(String(36))
    status       = Column(String(30), default="beklemede")  # beklemede | islendi | iptal
    invoice_id   = Column(String(36), nullable=True)
    company_id   = Column(String(36))
    created_at   = Column(DateTime, default=datetime.utcnow)
