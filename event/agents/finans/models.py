"""
Finans Ajanı — Veri Modelleri

Modüller:
  Project            — E-dem referansı ile proje
  BudgetLine         — Planlanan bütçe kalemleri
  ActualEntry        — Gerçekleşen gider/gelir
  PaymentPlan        — Ödeme planı takvimi
  SupplierAccount    — Tedarikçi cari hesabı
  SupplierPayment    — Tedarikçiye yapılan ödeme
  EFatura            — E-fatura kaydı
  EFaturaLine        — E-fatura satırı
  CashEntry          — Kasa hareketi
  CashDayReport      — Günlük kasa özeti (gün sonu)
  CreditCard         — Kredi kartı tanımı
  CreditCardTxn      — Kredi kartı hareketi
  CreditCardStatement — Ekstre
"""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey,
    Integer, String, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

BUDGET_CATEGORIES = [
    {"value": "accommodation", "label": "Konaklama"},
    {"value": "meeting",       "label": "Toplantı / Salon"},
    {"value": "fb",            "label": "F&B"},
    {"value": "teknik",        "label": "Teknik Ekipman"},
    {"value": "dekor",         "label": "Dekor / Süsleme"},
    {"value": "transfer",      "label": "Transfer / Ulaşım"},
    {"value": "tasarim",       "label": "Tasarım & Baskı"},
    {"value": "ik",            "label": "İnsan Kaynakları"},
    {"value": "other",         "label": "Diğer"},
]

PAYMENT_METHODS = [
    {"value": "havale",  "label": "Havale / EFT"},
    {"value": "nakit",   "label": "Nakit"},
    {"value": "kk",      "label": "Kredi Kartı"},
    {"value": "cek",     "label": "Çek"},
    {"value": "senet",   "label": "Senet"},
]

PAYMENT_PLAN_STATUSES = [
    {"value": "bekliyor",   "label": "Bekliyor"},
    {"value": "odendi",     "label": "Ödendi"},
    {"value": "gecikti",    "label": "Gecikti"},
    {"value": "iptal",      "label": "İptal"},
]

EFATURA_TYPES = [
    {"value": "satis",  "label": "Satış Faturası"},
    {"value": "alis",   "label": "Alış Faturası"},
    {"value": "iade",   "label": "İade Faturası"},
]

EFATURA_STATUSES = [
    {"value": "taslak",  "label": "Taslak"},
    {"value": "kesildi", "label": "Kesildi"},
    {"value": "iptal",   "label": "İptal"},
]

VAT_RATES = [0, 1, 8, 10, 18, 20]

CASH_ENTRY_TYPES = [
    {"value": "giris", "label": "Giriş"},
    {"value": "cikis", "label": "Çıkış"},
]

CASH_CATEGORIES = [
    {"value": "tahsilat",  "label": "Tahsilat"},
    {"value": "odeme",     "label": "Ödeme"},
    {"value": "avans",     "label": "Avans"},
    {"value": "masraf",    "label": "Masraf"},
    {"value": "diger",     "label": "Diğer"},
]

PROJECT_STATUSES = [
    {"value": "aktif",     "label": "Aktif"},
    {"value": "tamamlandi","label": "Tamamlandı"},
    {"value": "iptal",     "label": "İptal"},
]

SUPPLIER_STATUSES = [
    {"value": "aktif",  "label": "Aktif"},
    {"value": "pasif",  "label": "Pasif"},
]

CC_STATEMENT_STATUSES = [
    {"value": "bekliyor",  "label": "Bekliyor"},
    {"value": "odendi",    "label": "Ödendi"},
    {"value": "kismi",     "label": "Kısmi Ödendi"},
]

# Label lookup'ları
BUDGET_CATEGORY_LABELS  = {c["value"]: c["label"] for c in BUDGET_CATEGORIES}
PAYMENT_METHOD_LABELS   = {m["value"]: m["label"] for m in PAYMENT_METHODS}
PAYMENT_STATUS_LABELS   = {s["value"]: s["label"] for s in PAYMENT_PLAN_STATUSES}
EFATURA_TYPE_LABELS     = {t["value"]: t["label"] for t in EFATURA_TYPES}
EFATURA_STATUS_LABELS   = {s["value"]: s["label"] for s in EFATURA_STATUSES}
CASH_ENTRY_TYPE_LABELS  = {t["value"]: t["label"] for t in CASH_ENTRY_TYPES}
CASH_CATEGORY_LABELS    = {c["value"]: c["label"] for c in CASH_CATEGORIES}
PROJECT_STATUS_LABELS   = {s["value"]: s["label"] for s in PROJECT_STATUSES}
CC_STATEMENT_LABELS     = {s["value"]: s["label"] for s in CC_STATEMENT_STATUSES}


# ===========================================================================
# 1. Proje (E-dem referansı ile bağlantılı)
# ===========================================================================
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str]         = mapped_column(String, nullable=False)
    edem_request_id: Mapped[Optional[str]]  = mapped_column(String)
    edem_request_no: Mapped[Optional[str]]  = mapped_column(String)
    customer_name: Mapped[Optional[str]]    = mapped_column(String)
    event_date: Mapped[Optional[date]]      = mapped_column(Date)
    event_end_date: Mapped[Optional[date]]  = mapped_column(Date)
    status: Mapped[str]       = mapped_column(String, default="aktif")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    budget_lines: Mapped[list["BudgetLine"]]   = relationship(back_populates="project", cascade="all, delete-orphan")
    actual_entries: Mapped[list["ActualEntry"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    payment_plans: Mapped[list["PaymentPlan"]]  = relationship(back_populates="project", cascade="all, delete-orphan")

    @property
    def total_budgeted(self) -> float:
        return sum(bl.amount for bl in self.budget_lines)

    @property
    def total_actual(self) -> float:
        return sum(ae.amount for ae in self.actual_entries)

    @property
    def variance(self) -> float:
        return self.total_budgeted - self.total_actual

    @property
    def completion_pct(self) -> float:
        if self.total_budgeted == 0:
            return 0.0
        return min(round(self.total_actual / self.total_budgeted * 100, 1), 999.9)


# ===========================================================================
# 2. Bütçe Kalemi
# ===========================================================================
class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str]   = mapped_column(ForeignKey("projects.id"), nullable=False)
    category: Mapped[str]     = mapped_column(String, default="other")
    description: Mapped[str]  = mapped_column(String, nullable=False)
    amount: Mapped[float]     = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int]   = mapped_column(Integer, default=0)

    project: Mapped["Project"] = relationship(back_populates="budget_lines")
    actual_entries: Mapped[list["ActualEntry"]] = relationship(back_populates="budget_line")

    @property
    def actual_total(self) -> float:
        return sum(ae.amount for ae in self.actual_entries)

    @property
    def variance(self) -> float:
        return self.amount - self.actual_total


# ===========================================================================
# 3. Gerçekleşen Gider/Gelir
# ===========================================================================
class ActualEntry(Base):
    __tablename__ = "actual_entries"

    id: Mapped[str]                      = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str]              = mapped_column(ForeignKey("projects.id"), nullable=False)
    budget_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("budget_lines.id"))
    entry_date: Mapped[date]             = mapped_column(Date, nullable=False)
    description: Mapped[str]             = mapped_column(String, nullable=False)
    amount: Mapped[float]                = mapped_column(Float, default=0.0)
    category: Mapped[str]                = mapped_column(String, default="other")
    supplier_name: Mapped[Optional[str]] = mapped_column(String)
    invoice_no: Mapped[Optional[str]]    = mapped_column(String)
    payment_method: Mapped[Optional[str]] = mapped_column(String)
    notes: Mapped[Optional[str]]         = mapped_column(Text)
    created_at: Mapped[datetime]         = mapped_column(DateTime, default=_now)

    project: Mapped["Project"]             = relationship(back_populates="actual_entries")
    budget_line: Mapped[Optional["BudgetLine"]] = relationship(back_populates="actual_entries")


# ===========================================================================
# 4. Ödeme Planı
# ===========================================================================
class PaymentPlan(Base):
    __tablename__ = "payment_plans"

    id: Mapped[str]                     = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[Optional[str]]   = mapped_column(ForeignKey("projects.id"))
    supplier_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("supplier_accounts.id"))
    description: Mapped[str]            = mapped_column(String, nullable=False)
    amount: Mapped[float]               = mapped_column(Float, default=0.0)
    due_date: Mapped[date]              = mapped_column(Date, nullable=False)
    status: Mapped[str]                 = mapped_column(String, default="bekliyor")
    payment_date: Mapped[Optional[date]] = mapped_column(Date)
    payment_method: Mapped[Optional[str]] = mapped_column(String)
    notes: Mapped[Optional[str]]        = mapped_column(Text)
    created_at: Mapped[datetime]        = mapped_column(DateTime, default=_now)

    project: Mapped[Optional["Project"]]              = relationship(back_populates="payment_plans")
    supplier_account: Mapped[Optional["SupplierAccount"]] = relationship(back_populates="payment_plans")

    @property
    def is_overdue(self) -> bool:
        from datetime import date as _date
        return self.status == "bekliyor" and self.due_date < _date.today()


# ===========================================================================
# 5. Tedarikçi Cari Hesabı
# ===========================================================================
class SupplierAccount(Base):
    __tablename__ = "supplier_accounts"

    id: Mapped[str]                     = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str]                   = mapped_column(String, nullable=False)
    tax_number: Mapped[Optional[str]]   = mapped_column(String)
    tax_office: Mapped[Optional[str]]   = mapped_column(String)
    contact_name: Mapped[Optional[str]] = mapped_column(String)
    email: Mapped[Optional[str]]        = mapped_column(String)
    phone: Mapped[Optional[str]]        = mapped_column(String)
    iban: Mapped[Optional[str]]         = mapped_column(String)
    status: Mapped[str]                 = mapped_column(String, default="aktif")
    notes: Mapped[Optional[str]]        = mapped_column(Text)
    created_at: Mapped[datetime]        = mapped_column(DateTime, default=_now)

    payments: Mapped[list["SupplierPayment"]] = relationship(back_populates="supplier", cascade="all, delete-orphan")
    payment_plans: Mapped[list["PaymentPlan"]] = relationship(back_populates="supplier_account")

    @property
    def total_debt(self) -> float:
        """Toplam borç (tüm ödeme planlarından bekleyenler)."""
        return sum(p.amount for p in self.payment_plans if p.status == "bekliyor")

    @property
    def total_paid(self) -> float:
        return sum(p.amount for p in self.payments)


# ===========================================================================
# 6. Tedarikçi Ödemesi
# ===========================================================================
class SupplierPayment(Base):
    __tablename__ = "supplier_payments"

    id: Mapped[str]                   = mapped_column(String, primary_key=True, default=_uuid)
    supplier_id: Mapped[str]          = mapped_column(ForeignKey("supplier_accounts.id"), nullable=False)
    payment_date: Mapped[date]        = mapped_column(Date, nullable=False)
    amount: Mapped[float]             = mapped_column(Float, default=0.0)
    method: Mapped[str]               = mapped_column(String, default="havale")
    description: Mapped[str]         = mapped_column(String, default="")
    reference_no: Mapped[Optional[str]] = mapped_column(String)
    invoice_no: Mapped[Optional[str]]   = mapped_column(String)
    notes: Mapped[Optional[str]]      = mapped_column(Text)
    created_at: Mapped[datetime]      = mapped_column(DateTime, default=_now)

    supplier: Mapped["SupplierAccount"] = relationship(back_populates="payments")


# ===========================================================================
# 7. E-Fatura
# ===========================================================================
class EFatura(Base):
    __tablename__ = "efaturalar"

    id: Mapped[str]                        = mapped_column(String, primary_key=True, default=_uuid)
    invoice_no: Mapped[str]                = mapped_column(String, nullable=False, unique=True)
    invoice_date: Mapped[date]             = mapped_column(Date, nullable=False)
    invoice_type: Mapped[str]              = mapped_column(String, default="satis")  # satis/alis/iade
    status: Mapped[str]                    = mapped_column(String, default="taslak")

    # Düzenleyen (satıcı)
    seller_name: Mapped[str]               = mapped_column(String, nullable=False)
    seller_tax_no: Mapped[Optional[str]]   = mapped_column(String)
    seller_tax_office: Mapped[Optional[str]] = mapped_column(String)

    # Alıcı
    buyer_name: Mapped[str]                = mapped_column(String, nullable=False)
    buyer_tax_no: Mapped[Optional[str]]    = mapped_column(String)
    buyer_tax_office: Mapped[Optional[str]] = mapped_column(String)

    # Toplamlar
    total_excl_vat: Mapped[float]          = mapped_column(Float, default=0.0)
    total_vat: Mapped[float]               = mapped_column(Float, default=0.0)
    total_incl_vat: Mapped[float]          = mapped_column(Float, default=0.0)

    # Bağlantılar
    edem_request_no: Mapped[Optional[str]] = mapped_column(String)
    project_id: Mapped[Optional[str]]      = mapped_column(ForeignKey("projects.id"))
    notes: Mapped[Optional[str]]           = mapped_column(Text)
    created_at: Mapped[datetime]           = mapped_column(DateTime, default=_now)

    lines: Mapped[list["EFaturaLine"]] = relationship(back_populates="efatura", cascade="all, delete-orphan")


class EFaturaLine(Base):
    __tablename__ = "efatura_lines"

    id: Mapped[str]             = mapped_column(String, primary_key=True, default=_uuid)
    efatura_id: Mapped[str]     = mapped_column(ForeignKey("efaturalar.id"), nullable=False)
    description: Mapped[str]    = mapped_column(String, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String, default="Adet")
    qty: Mapped[float]          = mapped_column(Float, default=1.0)
    unit_price: Mapped[float]   = mapped_column(Float, default=0.0)
    vat_rate: Mapped[int]       = mapped_column(Integer, default=20)   # % olarak (20 = %20)
    amount_excl: Mapped[float]  = mapped_column(Float, default=0.0)   # qty * unit_price
    vat_amount: Mapped[float]   = mapped_column(Float, default=0.0)
    amount_incl: Mapped[float]  = mapped_column(Float, default=0.0)

    efatura: Mapped["EFatura"]  = relationship(back_populates="lines")


# ===========================================================================
# 8. Kasa Hareketi
# ===========================================================================
class CashEntry(Base):
    __tablename__ = "cash_entries"

    id: Mapped[str]                    = mapped_column(String, primary_key=True, default=_uuid)
    entry_date: Mapped[date]           = mapped_column(Date, nullable=False)
    entry_type: Mapped[str]            = mapped_column(String, nullable=False)  # giris / cikis
    amount: Mapped[float]              = mapped_column(Float, default=0.0)
    category: Mapped[str]              = mapped_column(String, default="diger")
    description: Mapped[str]           = mapped_column(String, nullable=False)
    reference_no: Mapped[Optional[str]] = mapped_column(String)
    related_party: Mapped[Optional[str]] = mapped_column(String)  # müşteri / tedarikçi adı
    day_report_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cash_day_reports.id"))
    notes: Mapped[Optional[str]]       = mapped_column(Text)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=_now)

    day_report: Mapped[Optional["CashDayReport"]] = relationship(back_populates="entries")


# ===========================================================================
# 9. Gün Sonu Kasa Raporu
# ===========================================================================
class CashDayReport(Base):
    __tablename__ = "cash_day_reports"

    id: Mapped[str]                    = mapped_column(String, primary_key=True, default=_uuid)
    report_date: Mapped[date]          = mapped_column(Date, nullable=False, unique=True)
    opening_balance: Mapped[float]     = mapped_column(Float, default=0.0)
    total_in: Mapped[float]            = mapped_column(Float, default=0.0)
    total_out: Mapped[float]           = mapped_column(Float, default=0.0)
    closing_balance: Mapped[float]     = mapped_column(Float, default=0.0)
    is_closed: Mapped[bool]            = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]]       = mapped_column(Text)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=_now)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    entries: Mapped[list["CashEntry"]] = relationship(back_populates="day_report")


# ===========================================================================
# 10. Kredi Kartı Tanımı
# ===========================================================================
class CreditCard(Base):
    __tablename__ = "credit_cards"

    id: Mapped[str]                    = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str]                  = mapped_column(String, nullable=False)   # "Yapı Kredi Kurumsal"
    bank: Mapped[Optional[str]]        = mapped_column(String)
    last_four: Mapped[Optional[str]]   = mapped_column(String(4))
    credit_limit: Mapped[float]        = mapped_column(Float, default=0.0)
    billing_day: Mapped[int]           = mapped_column(Integer, default=1)       # kesim günü (1-31)
    due_day_offset: Mapped[int]        = mapped_column(Integer, default=10)      # kesimden kaç gün sonra son ödeme
    is_active: Mapped[bool]            = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]]       = mapped_column(Text)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=_now)

    transactions: Mapped[list["CreditCardTxn"]]       = relationship(back_populates="card", cascade="all, delete-orphan")
    statements: Mapped[list["CreditCardStatement"]]   = relationship(back_populates="card", cascade="all, delete-orphan")

    @property
    def current_balance(self) -> float:
        """Tüm ödenmeyen harcamaların toplamı."""
        return sum(
            t.amount for t in self.transactions
            if not t.is_refund and t.statement_id is None
        )


# ===========================================================================
# 11. Kredi Kartı Hareketi
# ===========================================================================
class CreditCardTxn(Base):
    __tablename__ = "credit_card_txns"

    id: Mapped[str]                    = mapped_column(String, primary_key=True, default=_uuid)
    card_id: Mapped[str]               = mapped_column(ForeignKey("credit_cards.id"), nullable=False)
    statement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("credit_card_statements.id"))
    txn_date: Mapped[date]             = mapped_column(Date, nullable=False)
    description: Mapped[str]           = mapped_column(String, nullable=False)
    amount: Mapped[float]              = mapped_column(Float, default=0.0)
    category: Mapped[Optional[str]]    = mapped_column(String)
    is_refund: Mapped[bool]            = mapped_column(Boolean, default=False)
    installments: Mapped[int]          = mapped_column(Integer, default=1)       # taksit sayısı
    installment_no: Mapped[int]        = mapped_column(Integer, default=1)       # kaçıncı taksit
    notes: Mapped[Optional[str]]       = mapped_column(Text)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=_now)

    card: Mapped["CreditCard"]                         = relationship(back_populates="transactions")
    statement: Mapped[Optional["CreditCardStatement"]] = relationship(back_populates="transactions")


# ===========================================================================
# 12. Kredi Kartı Ekstresi
# ===========================================================================
class CreditCardStatement(Base):
    __tablename__ = "credit_card_statements"

    id: Mapped[str]                    = mapped_column(String, primary_key=True, default=_uuid)
    card_id: Mapped[str]               = mapped_column(ForeignKey("credit_cards.id"), nullable=False)
    statement_date: Mapped[date]       = mapped_column(Date, nullable=False)   # ekstre kesim tarihi
    due_date: Mapped[date]             = mapped_column(Date, nullable=False)   # son ödeme tarihi
    total_amount: Mapped[float]        = mapped_column(Float, default=0.0)
    minimum_payment: Mapped[float]     = mapped_column(Float, default=0.0)
    paid_amount: Mapped[float]         = mapped_column(Float, default=0.0)
    payment_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str]                = mapped_column(String, default="bekliyor")
    notes: Mapped[Optional[str]]       = mapped_column(Text)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=_now)

    card: Mapped["CreditCard"]                       = relationship(back_populates="statements")
    transactions: Mapped[list["CreditCardTxn"]]      = relationship(back_populates="statement")

    @property
    def remaining(self) -> float:
        return self.total_amount - self.paid_amount

    @property
    def is_overdue(self) -> bool:
        from datetime import date as _date
        return self.status != "odendi" and self.due_date < _date.today()
