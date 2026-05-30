"""
HR Ajanı — Veri Modelleri

Modüller:
  HRUser            — Kullanıcı (hr_admin, hr_manager, employee)
  Employee          — Çalışan
  PersonnelDocument — Özlük belgesi
  Asset             — Zimmet kaydı
  LeaveRequest      — İzin talebi
  LeaveBalance      — Yıllık izin bakiyesi
  OvertimeRecord    — Fazla mesai
  PayrollRecord     — Bordro
  MealCard          — Yemek kartı yüklemesi
  FlexibleBenefit   — Esnek yan hak havuzu
  BenefitSpending   — Esnek yan hak harcaması
  Notification      — In-app bildirim
  AdvanceRequest    — Maaş / İş avansı talebi
"""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

ROLES = [
    {"value": "hr_admin",   "label": "HR Admin"},
    {"value": "hr_manager", "label": "HR Yöneticisi"},
    {"value": "employee",   "label": "Çalışan"},
]

EMPLOYMENT_TYPES = [
    {"value": "tam_zamanli",  "label": "Tam Zamanlı"},
    {"value": "yari_zamanli", "label": "Yarı Zamanlı"},
    {"value": "stajyer",      "label": "Stajyer"},
]

EMPLOYEE_STATUSES = [
    {"value": "aktif",    "label": "Aktif"},
    {"value": "izinli",   "label": "İzinde"},
    {"value": "ayrilmis", "label": "Ayrılmış"},
]

DOC_TYPES = [
    {"value": "sozlesme",   "label": "İş Sözleşmesi"},
    {"value": "sgk",        "label": "SGK Belgesi"},
    {"value": "kimlik",     "label": "Kimlik Fotokopisi"},
    {"value": "diploma",    "label": "Diploma"},
    {"value": "performans", "label": "Performans Değerlendirmesi"},
    {"value": "diger",      "label": "Diğer"},
]

ASSET_TYPES = [
    {"value": "laptop",    "label": "Laptop / Bilgisayar"},
    {"value": "telefon",   "label": "Cep Telefonu"},
    {"value": "arac",      "label": "Araç"},
    {"value": "aksesuar",  "label": "Aksesuar"},
    {"value": "diger",     "label": "Diğer"},
]

ASSET_CONDITIONS = [
    {"value": "iyi",    "label": "İyi"},
    {"value": "hasarli","label": "Hasarlı"},
    {"value": "kayip",  "label": "Kayıp"},
]

LEAVE_TYPES = [
    {"value": "yillik",  "label": "Yıllık İzin"},
    {"value": "mazeret", "label": "Mazeret İzni"},
    {"value": "hastalik","label": "Hastalık İzni"},
    {"value": "ucretsiz","label": "Ücretsiz İzin"},
    {"value": "dogum",   "label": "Doğum İzni"},
    {"value": "olum",    "label": "Ölüm İzni"},
]

LEAVE_STATUSES = [
    {"value": "beklemede", "label": "Beklemede"},
    {"value": "onaylandi", "label": "Onaylandı"},
    {"value": "reddedildi","label": "Reddedildi"},
    {"value": "iptal",     "label": "İptal"},
]

OVERTIME_RATES = [
    {"value": 1.5, "label": "1.5x (Normal Mesai)"},
    {"value": 2.0, "label": "2.0x (Tatil Mesaisi)"},
]

PAYROLL_STATUSES = [
    {"value": "taslak",    "label": "Taslak"},
    {"value": "onaylandi", "label": "Onaylandı"},
    {"value": "odendi",    "label": "Ödendi"},
]

MEAL_PROVIDERS = [
    {"value": "Ticket",   "label": "Ticket Restaurant"},
    {"value": "Sodexo",   "label": "Sodexo"},
    {"value": "Multinet", "label": "Multinet"},
    {"value": "Edenred",  "label": "Edenred"},
    {"value": "Diger",    "label": "Diğer"},
]

BENEFIT_CATEGORIES = [
    {"value": "saglik",  "label": "Sağlık & Sigorta"},
    {"value": "spor",    "label": "Spor & Fitness"},
    {"value": "egitim",  "label": "Eğitim & Gelişim"},
    {"value": "ulasim",  "label": "Ulaşım"},
    {"value": "market",  "label": "Market & Alışveriş"},
    {"value": "diger",   "label": "Diğer"},
]

NOTIFICATION_TYPES = [
    {"value": "izin_talebi",    "label": "Yeni İzin Talebi"},
    {"value": "izin_onay",      "label": "İzin Kararı"},
    {"value": "overtime_talebi","label": "Yeni Overtime Talebi"},
    {"value": "overtime_onay",  "label": "Overtime Kararı"},
    {"value": "zimmet",         "label": "Zimmet Bildirimi"},
    {"value": "bordro",         "label": "Bordro Hazır"},
    {"value": "avans_talebi",   "label": "Yeni Avans Talebi"},
    {"value": "avans_onay",     "label": "Avans Kararı"},
    {"value": "avans_odendi",   "label": "Avans Ödendi"},
]

ADVANCE_TYPES = [
    {"value": "maas", "label": "Maaş Avansı"},
    {"value": "is",   "label": "İş Avansı"},
]

ADVANCE_STATUSES = [
    {"value": "beklemede", "label": "Beklemede"},
    {"value": "onaylandi", "label": "Onaylandı"},
    {"value": "reddedildi","label": "Reddedildi"},
    {"value": "odendi",    "label": "Ödendi"},
    {"value": "kapandi",   "label": "Kapatıldı"},
    {"value": "iptal",     "label": "İptal"},
]

SALARY_ADVANCE_LIMIT_RATE = 0.30   # Brüt maaşın %30'u

# Label lookup'ları
ROLE_LABELS          = {r["value"]: r["label"] for r in ROLES}
EMP_TYPE_LABELS      = {t["value"]: t["label"] for t in EMPLOYMENT_TYPES}
EMP_STATUS_LABELS    = {s["value"]: s["label"] for s in EMPLOYEE_STATUSES}
DOC_TYPE_LABELS      = {d["value"]: d["label"] for d in DOC_TYPES}
ASSET_TYPE_LABELS    = {a["value"]: a["label"] for a in ASSET_TYPES}
ASSET_COND_LABELS    = {c["value"]: c["label"] for c in ASSET_CONDITIONS}
LEAVE_TYPE_LABELS    = {l["value"]: l["label"] for l in LEAVE_TYPES}
LEAVE_STATUS_LABELS  = {s["value"]: s["label"] for s in LEAVE_STATUSES}
PAYROLL_STATUS_LABELS  = {s["value"]: s["label"] for s in PAYROLL_STATUSES}
BENEFIT_CAT_LABELS     = {c["value"]: c["label"] for c in BENEFIT_CATEGORIES}
ADVANCE_TYPE_LABELS    = {t["value"]: t["label"] for t in ADVANCE_TYPES}
ADVANCE_STATUS_LABELS  = {s["value"]: s["label"] for s in ADVANCE_STATUSES}


# ===========================================================================
# 1. Kullanıcı (HR sistemine giriş yapanlar)
# ===========================================================================
class HRUser(Base):
    __tablename__ = "hr_users"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str]        = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str]         = mapped_column(String, default="employee")  # hr_admin | hr_manager | employee
    employee_id: Mapped[Optional[str]] = mapped_column(ForeignKey("employees.id"))  # bağlı çalışan
    is_active: Mapped[bool]   = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    employee: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[employee_id], back_populates="user"
    )

    @property
    def display_name(self) -> str:
        if self.employee:
            return f"{self.employee.first_name} {self.employee.last_name}"
        return self.email.split("@")[0]

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


# ===========================================================================
# 2. Çalışan
# ===========================================================================
class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str]                    = mapped_column(String, primary_key=True, default=_uuid)
    employee_no: Mapped[str]           = mapped_column(String, unique=True, nullable=False)  # EMP-001
    first_name: Mapped[str]            = mapped_column(String, nullable=False)
    last_name: Mapped[str]             = mapped_column(String, nullable=False)
    email: Mapped[str]                 = mapped_column(String, unique=True, nullable=False)
    phone: Mapped[Optional[str]]       = mapped_column(String)
    tc_no: Mapped[Optional[str]]       = mapped_column(String)
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    hire_date: Mapped[date]            = mapped_column(Date, nullable=False)
    termination_date: Mapped[Optional[date]] = mapped_column(Date)
    department: Mapped[Optional[str]]  = mapped_column(String)
    title: Mapped[Optional[str]]       = mapped_column(String)
    manager_id: Mapped[Optional[str]]  = mapped_column(ForeignKey("employees.id"))
    employment_type: Mapped[str]       = mapped_column(String, default="tam_zamanli")
    status: Mapped[str]                = mapped_column(String, default="aktif")
    annual_leave_days: Mapped[int]     = mapped_column(Integer, default=14)
    gross_salary: Mapped[float]        = mapped_column(Float, default=0.0)
    photo_url: Mapped[Optional[str]]   = mapped_column(String)
    notes: Mapped[Optional[str]]       = mapped_column(Text)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime]       = mapped_column(DateTime, default=_now, onupdate=_now)

    # İlişkiler
    manager: Mapped[Optional["Employee"]]        = relationship("Employee", remote_side="Employee.id", foreign_keys=[manager_id])
    user: Mapped[Optional["HRUser"]]             = relationship("HRUser", foreign_keys="HRUser.employee_id", back_populates="employee")
    documents: Mapped[list["PersonnelDocument"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]]                = relationship(back_populates="employee", cascade="all, delete-orphan")
    leave_requests: Mapped[list["LeaveRequest"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    leave_balances: Mapped[list["LeaveBalance"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    overtime_records: Mapped[list["OvertimeRecord"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    payroll_records: Mapped[list["PayrollRecord"]]   = relationship(back_populates="employee", cascade="all, delete-orphan")
    meal_cards: Mapped[list["MealCard"]]             = relationship(back_populates="employee", cascade="all, delete-orphan")
    flexible_benefits: Mapped[list["FlexibleBenefit"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    advance_requests: Mapped[list["AdvanceRequest"]]   = relationship(back_populates="employee", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def active_assets(self) -> list:
        return [a for a in self.assets if a.returned_date is None]

    @property
    def status_label(self) -> str:
        return EMP_STATUS_LABELS.get(self.status, self.status)

    @property
    def employment_type_label(self) -> str:
        return EMP_TYPE_LABELS.get(self.employment_type, self.employment_type)


# ===========================================================================
# 3. Özlük Belgesi
# ===========================================================================
class PersonnelDocument(Base):
    __tablename__ = "personnel_documents"

    id: Mapped[str]              = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]     = mapped_column(ForeignKey("employees.id"), nullable=False)
    doc_type: Mapped[str]        = mapped_column(String, default="diger")
    title: Mapped[str]           = mapped_column(String, nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String)
    file_path: Mapped[Optional[str]] = mapped_column(String)
    uploaded_by: Mapped[Optional[str]] = mapped_column(ForeignKey("hr_users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship(back_populates="documents")

    @property
    def doc_type_label(self) -> str:
        return DOC_TYPE_LABELS.get(self.doc_type, self.doc_type)


# ===========================================================================
# 4. Zimmet
# ===========================================================================
class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str]                       = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]              = mapped_column(ForeignKey("employees.id"), nullable=False)
    asset_type: Mapped[str]               = mapped_column(String, default="diger")
    brand: Mapped[Optional[str]]          = mapped_column(String)
    model: Mapped[Optional[str]]          = mapped_column(String)
    serial_no: Mapped[Optional[str]]      = mapped_column(String)
    assigned_date: Mapped[date]           = mapped_column(Date, nullable=False)
    returned_date: Mapped[Optional[date]] = mapped_column(Date)
    condition: Mapped[str]                = mapped_column(String, default="iyi")
    notes: Mapped[Optional[str]]          = mapped_column(Text)
    signed: Mapped[bool]                  = mapped_column(Boolean, default=False)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime]          = mapped_column(DateTime, default=_now)

    employee: Mapped["Employee"] = relationship(back_populates="assets")

    @property
    def asset_type_label(self) -> str:
        return ASSET_TYPE_LABELS.get(self.asset_type, self.asset_type)

    @property
    def condition_label(self) -> str:
        return ASSET_COND_LABELS.get(self.condition, self.condition)

    @property
    def is_active(self) -> bool:
        return self.returned_date is None

    @property
    def description(self) -> str:
        parts = [p for p in [self.brand, self.model] if p]
        return " ".join(parts) if parts else self.asset_type_label


# ===========================================================================
# 5. İzin Talebi
# ===========================================================================
class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[str]                        = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]               = mapped_column(ForeignKey("employees.id"), nullable=False)
    leave_type: Mapped[str]                = mapped_column(String, default="yillik")
    start_date: Mapped[date]               = mapped_column(Date, nullable=False)
    end_date: Mapped[date]                 = mapped_column(Date, nullable=False)
    days: Mapped[int]                      = mapped_column(Integer, default=1)
    reason: Mapped[Optional[str]]          = mapped_column(Text)
    status: Mapped[str]                    = mapped_column(String, default="beklemede")
    reviewed_by: Mapped[Optional[str]]     = mapped_column(ForeignKey("hr_users.id"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    reviewer_note: Mapped[Optional[str]]   = mapped_column(Text)
    created_at: Mapped[datetime]           = mapped_column(DateTime, default=_now)

    employee: Mapped["Employee"] = relationship(back_populates="leave_requests")

    @property
    def leave_type_label(self) -> str:
        return LEAVE_TYPE_LABELS.get(self.leave_type, self.leave_type)

    @property
    def status_label(self) -> str:
        return LEAVE_STATUS_LABELS.get(self.status, self.status)


# ===========================================================================
# 6. İzin Bakiyesi
# ===========================================================================
class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]  = mapped_column(ForeignKey("employees.id"), nullable=False)
    year: Mapped[int]         = mapped_column(Integer, nullable=False)
    total_days: Mapped[int]   = mapped_column(Integer, default=14)
    used_days: Mapped[int]    = mapped_column(Integer, default=0)
    pending_days: Mapped[int] = mapped_column(Integer, default=0)

    employee: Mapped["Employee"] = relationship(back_populates="leave_balances")

    @property
    def remaining_days(self) -> int:
        return max(0, self.total_days - self.used_days - self.pending_days)


# ===========================================================================
# 7. Fazla Mesai
# ===========================================================================
class OvertimeRecord(Base):
    __tablename__ = "overtime_records"

    id: Mapped[str]                        = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]               = mapped_column(ForeignKey("employees.id"), nullable=False)
    work_date: Mapped[date]                = mapped_column(Date, nullable=False)
    hours: Mapped[float]                   = mapped_column(Float, default=0.0)
    reason: Mapped[Optional[str]]          = mapped_column(Text)
    rate: Mapped[float]                    = mapped_column(Float, default=1.5)
    status: Mapped[str]                    = mapped_column(String, default="beklemede")
    approved_by: Mapped[Optional[str]]     = mapped_column(ForeignKey("hr_users.id"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    payroll_id: Mapped[Optional[str]]      = mapped_column(ForeignKey("payroll_records.id"))
    created_at: Mapped[datetime]           = mapped_column(DateTime, default=_now)

    employee: Mapped["Employee"] = relationship(back_populates="overtime_records")

    @property
    def rate_label(self) -> str:
        return "1.5x (Normal)" if self.rate == 1.5 else "2.0x (Tatil)"


# ===========================================================================
# 8. Bordro
# ===========================================================================
class PayrollRecord(Base):
    __tablename__ = "payroll_records"

    id: Mapped[str]                        = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]               = mapped_column(ForeignKey("employees.id"), nullable=False)
    period_year: Mapped[int]               = mapped_column(Integer, nullable=False)
    period_month: Mapped[int]              = mapped_column(Integer, nullable=False)
    gross_salary: Mapped[float]            = mapped_column(Float, default=0.0)   # Baz Ücret (Brüt)
    # Ek ödemeler
    overtime_pay: Mapped[float]            = mapped_column(Float, default=0.0)
    meal_allowance: Mapped[float]          = mapped_column(Float, default=0.0)   # Nakit yemek (SGK dahil)
    meal_allowance_ayni: Mapped[float]     = mapped_column(Float, default=0.0)   # Ayni yemek (SGK hariç)
    other_additions: Mapped[float]         = mapped_column(Float, default=0.0)   # Diğer ekler (dil, vs.)
    other_deductions: Mapped[float]        = mapped_column(Float, default=0.0)   # Özel kesintiler
    # Hesaplanan ara değerler
    total_gross: Mapped[float]             = mapped_column(Float, default=0.0)   # Tüm Gelirler Toplamı
    sgk_monthly_base: Mapped[float]        = mapped_column(Float, default=0.0)   # SGK Aylık Matrahı
    gv_monthly_base: Mapped[float]         = mapped_column(Float, default=0.0)   # GV Aylık Matrahı
    cumulative_gv_base: Mapped[float]      = mapped_column(Float, default=0.0)   # Kümülatif GV Matrahı (bu ay dahil)
    asgari_ucret_istisnasi_gv: Mapped[float] = mapped_column(Float, default=0.0)
    asgari_ucret_istisnasi_dv: Mapped[float] = mapped_column(Float, default=0.0)
    # Kesintiler
    sgk_employee: Mapped[float]            = mapped_column(Float, default=0.0)   # Çalışan SGK %7.5
    sgk_employer: Mapped[float]            = mapped_column(Float, default=0.0)   # İşveren SGK %24.75
    income_tax: Mapped[float]              = mapped_column(Float, default=0.0)
    stamp_tax: Mapped[float]               = mapped_column(Float, default=0.0)
    # Sonuçlar
    ele_gecen_ucret: Mapped[float]         = mapped_column(Float, default=0.0)   # Ele Geçen Ücret
    net_salary: Mapped[float]              = mapped_column(Float, default=0.0)   # Aylık Maaş (Net)
    payment_date: Mapped[Optional[date]]   = mapped_column(Date)
    status: Mapped[str]                    = mapped_column(String, default="taslak")
    notes: Mapped[Optional[str]]           = mapped_column(Text)
    created_at: Mapped[datetime]           = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime]           = mapped_column(DateTime, default=_now, onupdate=_now)

    employee: Mapped["Employee"] = relationship(back_populates="payroll_records")

    @property
    def status_label(self) -> str:
        return PAYROLL_STATUS_LABELS.get(self.status, self.status)

    @property
    def period_label(self) -> str:
        months = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                  "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        return f"{months[self.period_month]} {self.period_year}"

    @property
    def tesvikli_maliyet(self) -> float:
        return round(self.total_gross + self.sgk_employer, 2)

    @property
    def total_deductions(self) -> float:
        return self.sgk_employee + self.income_tax + self.stamp_tax + self.other_deductions

    @property
    def total_additions(self) -> float:
        return self.gross_salary + self.overtime_pay + self.meal_allowance + self.meal_allowance_ayni + self.other_additions


# ===========================================================================
# 9. Yemek Kartı Yüklemesi
# ===========================================================================
class MealCard(Base):
    __tablename__ = "meal_cards"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]  = mapped_column(ForeignKey("employees.id"), nullable=False)
    card_no: Mapped[Optional[str]] = mapped_column(String)
    provider: Mapped[str]     = mapped_column(String, default="Ticket")
    monthly_limit: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float]     = mapped_column(Float, default=0.0)
    loaded_at: Mapped[date]   = mapped_column(Date, nullable=False)
    period_year: Mapped[int]  = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    employee: Mapped["Employee"] = relationship(back_populates="meal_cards")

    @property
    def period_label(self) -> str:
        months = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                  "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        return f"{months[self.period_month]} {self.period_year}"


# ===========================================================================
# 10. Esnek Yan Hak Havuzu
# ===========================================================================
class FlexibleBenefit(Base):
    __tablename__ = "flexible_benefits"

    id: Mapped[str]           = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]  = mapped_column(ForeignKey("employees.id"), nullable=False)
    year: Mapped[int]         = mapped_column(Integer, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    used_points: Mapped[int]  = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    employee: Mapped["Employee"] = relationship(back_populates="flexible_benefits")
    spendings: Mapped[list["BenefitSpending"]] = relationship(
        back_populates="benefit", cascade="all, delete-orphan"
    )

    @property
    def remaining_points(self) -> int:
        return max(0, self.total_points - self.used_points)

    @property
    def usage_pct(self) -> float:
        if self.total_points == 0:
            return 0.0
        return round(self.used_points / self.total_points * 100, 1)


# ===========================================================================
# 11. Esnek Yan Hak Harcaması
# ===========================================================================
class BenefitSpending(Base):
    __tablename__ = "benefit_spendings"

    id: Mapped[str]                   = mapped_column(String, primary_key=True, default=_uuid)
    flexible_benefit_id: Mapped[str]  = mapped_column(ForeignKey("flexible_benefits.id"), nullable=False)
    category: Mapped[str]             = mapped_column(String, default="diger")
    description: Mapped[str]          = mapped_column(String, nullable=False)
    points: Mapped[int]               = mapped_column(Integer, default=0)
    spend_date: Mapped[date]          = mapped_column(Date, nullable=False)
    receipt_path: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime]      = mapped_column(DateTime, default=_now)

    benefit: Mapped["FlexibleBenefit"] = relationship(back_populates="spendings")

    @property
    def category_label(self) -> str:
        return BENEFIT_CAT_LABELS.get(self.category, self.category)


# ===========================================================================
# 12. In-App Bildirim
# ===========================================================================
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str]             = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str]        = mapped_column(ForeignKey("hr_users.id"), nullable=False)
    notif_type: Mapped[str]     = mapped_column(String, default="diger")
    title: Mapped[str]          = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    ref_type: Mapped[Optional[str]] = mapped_column(String)   # 'leave' | 'overtime' | 'asset' | 'payroll'
    ref_id: Mapped[Optional[str]]   = mapped_column(String)
    is_read: Mapped[bool]       = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ===========================================================================
# 13. Avans Talebi (Maaş Avansı / İş Avansı)
# ===========================================================================
class AdvanceRequest(Base):
    __tablename__ = "advance_requests"

    id: Mapped[str]                        = mapped_column(String, primary_key=True, default=_uuid)
    employee_id: Mapped[str]               = mapped_column(ForeignKey("employees.id"), nullable=False)
    advance_type: Mapped[str]              = mapped_column(String, nullable=False)   # 'maas' | 'is'
    amount: Mapped[float]                  = mapped_column(Float, nullable=False)
    reason: Mapped[Optional[str]]          = mapped_column(Text)
    request_date: Mapped[date]             = mapped_column(Date, nullable=False)
    needed_by: Mapped[Optional[date]]      = mapped_column(Date)                     # ne zaman gerekiyor

    # Onay
    status: Mapped[str]                    = mapped_column(String, default="beklemede")
    reviewed_by: Mapped[Optional[str]]     = mapped_column(ForeignKey("hr_users.id"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    reviewer_note: Mapped[Optional[str]]   = mapped_column(Text)

    # Ödeme
    payment_date: Mapped[Optional[date]]   = mapped_column(Date)
    paid_by: Mapped[Optional[str]]         = mapped_column(ForeignKey("hr_users.id"))

    # Maaş avansı — geri ödeme planı (bordrodan kesinti)
    repayment_months: Mapped[Optional[int]]      = mapped_column(Integer)   # kaç ayda
    repayment_start_year: Mapped[Optional[int]]  = mapped_column(Integer)
    repayment_start_month: Mapped[Optional[int]] = mapped_column(Integer)
    repaid_amount: Mapped[float]                 = mapped_column(Float, default=0.0)

    # İş avansı — kapatma (harcama belgesiyle)
    closed_at: Mapped[Optional[datetime]]  = mapped_column(DateTime)
    closing_notes: Mapped[Optional[str]]   = mapped_column(Text)
    remaining_amount: Mapped[float]        = mapped_column(Float, default=0.0)  # iade/fark

    created_at: Mapped[datetime]           = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime]           = mapped_column(DateTime, default=_now, onupdate=_now)

    employee: Mapped["Employee"] = relationship(back_populates="advance_requests")

    @property
    def advance_type_label(self) -> str:
        return ADVANCE_TYPE_LABELS.get(self.advance_type, self.advance_type)

    @property
    def status_label(self) -> str:
        return ADVANCE_STATUS_LABELS.get(self.status, self.status)

    @property
    def repayment_monthly(self) -> float:
        """Aylık bordro kesinti tutarı."""
        if self.advance_type != "maas" or not self.repayment_months:
            return 0.0
        return round(self.amount / self.repayment_months, 2)

    @property
    def remaining_repayment(self) -> float:
        """Henüz geri ödenmemiş maaş avansı tutarı."""
        return max(0.0, self.amount - self.repaid_amount)

    @property
    def repayment_label(self) -> str:
        months = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                  "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        if not self.repayment_start_year:
            return "—"
        m = months[self.repayment_start_month] if self.repayment_start_month else "?"
        return f"{m} {self.repayment_start_year} ({self.repayment_months} ay)"
