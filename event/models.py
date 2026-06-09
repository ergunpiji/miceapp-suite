"""
miceapp
SQLAlchemy modelleri ve uygulama sabitleri
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, Float
)
from sqlalchemy.orm import relationship, declarative_base

from roles import CANONICAL_ROLES  # kanonik rol kaynağı (event + desk ortak)

Base = declarative_base()


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

SUPPLIER_TYPES = [
    {"value": "otel",       "label": "Otel"},
    {"value": "etkinlik",   "label": "Etkinlik Mekanı"},
    {"value": "restaurant", "label": "Restoran"},
    {"value": "teknik",     "label": "Teknik Ekipman"},
    {"value": "dekor",      "label": "Dekor / Süsleme"},
    {"value": "transfer",   "label": "Transfer / Ulaşım"},
    {"value": "tasarim",    "label": "Tasarım & Baskı"},
    {"value": "susleme",    "label": "Süsleme"},
    {"value": "ik",         "label": "İnsan Kaynakları"},
    {"value": "diger",      "label": "Diğer"},
]

REQUEST_STATUSES = [
    {"value": "draft",             "label": "Taslak",                   "color": "secondary"},
    {"value": "pending",           "label": "Beklemede",                 "color": "warning"},
    {"value": "in_progress",       "label": "İşlemde",                   "color": "primary"},
    {"value": "venues_contacted",  "label": "Mekanlarla İletişime Geçildi", "color": "info"},
    {"value": "budget_ready",      "label": "Bütçe Hazır",               "color": "success"},
    {"value": "offer_sent",        "label": "Teklif Gönderildi",         "color": "teal"},
    {"value": "confirmed",         "label": "Müşteri Onayladı",          "color": "success"},
    {"value": "revision",          "label": "Revizyon",                  "color": "warning"},
    {"value": "completed",         "label": "Tamamlandı",                "color": "success"},
    {"value": "closing",           "label": "Kapama Onayında",           "color": "purple"},
    {"value": "closed",            "label": "Kapatıldı",                 "color": "dark"},
    {"value": "cancelled",         "label": "İptal Edildi",              "color": "danger"},
    {"value": "postponed",         "label": "Ertelendi",                 "color": "secondary"},
    {"value": "fund_pool",         "label": "Fon Havuzu",                "color": "teal"},
]

REQUEST_STATUS_COLORS = {s["value"]: s["color"] for s in REQUEST_STATUSES}
REQUEST_STATUS_LABELS = {s["value"]: s["label"] for s in REQUEST_STATUSES}

REQUEST_TABS = [
    {
        "id": "venue",
        "label": "🏨 Otel / Mekan",
        "supplier_types": ["otel", "etkinlik"],
        "sections": ["accommodation", "meeting", "fb"],
    },
    {
        "id": "teknik",
        "label": "🔧 Teknik Ekipman",
        "supplier_types": ["teknik"],
        "sections": ["teknik"],
    },
    {
        "id": "dekor",
        "label": "🎨 Dekor",
        "supplier_types": ["dekor"],
        "sections": ["dekor"],
    },
    {
        "id": "transfer",
        "label": "🚌 Ulaşım & Transferler",
        "supplier_types": ["transfer"],
        "sections": ["transfer"],
    },
    {
        "id": "tasarim",
        "label": "🖨 Tasarım & Basılı",
        "supplier_types": ["tasarim"],
        "sections": ["tasarim"],
    },
    {
        "id": "diger",
        "label": "📦 Diğer Servisler",
        "supplier_types": ["restaurant", "susleme", "ik", "diger"],
        "sections": ["other"],
    },
]

SEATING_LAYOUTS = [
    {"value": "tiyatro",    "label": "Tiyatro Düzeni"},
    {"value": "sinif",      "label": "Sınıf Düzeni"},
    {"value": "u-seklinde", "label": "U Şeklinde"},
    {"value": "toplanti",   "label": "Toplantı Düzeni"},
    {"value": "adatr",      "label": "Ada / Roundtable"},
    {"value": "kokteyl",    "label": "Kokteyl"},
    {"value": "gala",       "label": "Gala Oturma"},
]

EVENT_TYPES = [
    {"value": "toplanti",  "label": "Toplantı"},
    {"value": "konferans", "label": "Konferans"},
    {"value": "gala",      "label": "Gala"},
    {"value": "egitim",    "label": "Eğitim"},
    {"value": "lansman",   "label": "Lansman"},
    {"value": "diger",     "label": "Diğer"},
]

EVENT_TYPE_CODES = {
    "toplanti": "TOP",
    "konferans": "KON",
    "gala":      "GAL",
    "egitim":    "EGT",
    "lansman":   "LAN",
    "diger":     "ETK",
}


# Kanonik rol listesi (event + desk ortak). genel_mudur/super_admin/kullanici
# dahil — artık admin panelinden atanabilir (eski GM yamaları bu yüzden gerekiyordu).
USER_ROLES = list(CANONICAL_ROLES)

# Proje tarafı rollerin yetki seviyeleri (yüksek = daha fazla yetki)
PM_ROLE_LEVELS = {"mudur": 3, "yonetici": 2, "asistan": 1}

# OrgTitle → varsayılan rol önerisi
ORG_TITLE_PM_LEVELS = {
    "Genel Müdür":                "mudur",
    "Genel Müdür Yardımcısı":    "mudur",
    "Birim Müdürü":               "mudur",
    "Direktör":                   "mudur",
    "Kıdemli Proje Yöneticisi":  "yonetici",
    "Proje Yöneticisi":           "yonetici",
    "Proje Sorumlusu":            "yonetici",
    "Proje Asistanı":             "asistan",
    "Koordinatör":                "asistan",
}

USER_ROLE_LABELS = {r["value"]: r["label"] for r in USER_ROLES}

INVOICE_TYPES = [
    {"value": "kesilen",        "label": "Kesilen Fatura (Müşteriye)"},
    {"value": "gelen",          "label": "Gelen Fatura (Tedarikçiden)"},
    {"value": "komisyon",       "label": "Komisyon Faturası"},
    {"value": "iade_kesilen",   "label": "İade — Kesilen Fatura"},
    {"value": "iade_gelen",     "label": "İade — Gelen Fatura"},
    {"value": "belgesiz_gelir", "label": "Belgesiz Gelir"},
    {"value": "belgesiz_gider", "label": "Belgesiz Gider"},
]

BELGESIZ_TYPES = {"belgesiz_gelir", "belgesiz_gider"}

INVOICE_TYPE_LABELS = {t["value"]: t["label"] for t in INVOICE_TYPES}

SERVICE_CATEGORIES = [
    {"id": "accommodation", "label": "Konaklama",        "icon": "🛏",  "color": "primary"},
    {"id": "meeting",       "label": "Toplantı / Salon", "icon": "🏛",  "color": "success"},
    {"id": "fb",            "label": "F&B (Yiyecek & İçecek)", "icon": "🍽", "color": "warning"},
    {"id": "teknik",        "label": "Teknik",           "icon": "🔧",  "color": "danger"},
    {"id": "dekor",         "label": "Dekor",            "icon": "🎨",  "color": "pink"},
    {"id": "transfer",      "label": "Transfer",         "icon": "🚌",  "color": "info"},
    {"id": "tasarim",       "label": "Tasarım & Baskı",  "icon": "🖨",  "color": "green"},
    {"id": "other",         "label": "Diğer",            "icon": "📦",  "color": "purple"},
]

TR_CITIES = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya", "Ankara", "Antalya", "Artvin",
    "Aydın", "Balıkesir", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa", "Çanakkale",
    "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Edirne", "Elazığ", "Erzincan", "Erzurum",
    "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Isparta", "Mersin",
    "İstanbul", "İzmir", "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir", "Kocaeli",
    "Konya", "Kütahya", "Malatya", "Manisa", "Kahramanmaraş", "Mardin", "Muğla", "Muş",
    "Nevşehir", "Niğde", "Ordu", "Rize", "Sakarya", "Samsun", "Siirt", "Sinop", "Sivas",
    "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van", "Yozgat", "Zonguldak",
    "Aksaray", "Bayburt", "Karaman", "Kırıkkale", "Batman", "Şırnak", "Bartın", "Ardahan",
    "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye", "Düzce",
]

VAT_RATES = [0, 1, 8, 10, 18, 20]


# ---------------------------------------------------------------------------
# SQLAlchemy Modelleri
# ---------------------------------------------------------------------------

class Team(Base):
    """Etkinlik takımı — mudur + yonetici(ler) + asistan(lar)"""
    __tablename__ = "teams"

    id                  = Column(String(36), primary_key=True, default=_uuid)
    name                = Column(String(200), nullable=False)
    code                = Column(String(50), default="")
    description         = Column(Text, default="")
    active              = Column(Boolean, default=True, nullable=False)
    is_support_team     = Column(Boolean, default=False, nullable=False)
    company_id          = Column(String(36), nullable=True, index=True)   # tenant izolasyonu
    created_at          = Column(DateTime, default=_now, nullable=False)

    members = relationship("User", back_populates="team", foreign_keys="User.team_id")

    @property
    def mudur(self):
        """Takımın birim müdürü (varsa)."""
        for m in self.members:
            if m.role == "mudur" and m.active:
                return m
        return None

    @property
    def active_members(self):
        return [m for m in self.members if m.active]


class OrgTitle(Base):
    """Organizasyon unvanları — hiyerarşik yapı ve bütçe limitleri"""
    __tablename__ = "org_titles"

    id                 = Column(String(36), primary_key=True, default=_uuid)
    name               = Column(String(150), nullable=False)
    grade              = Column(Integer, nullable=False, default=1)   # 1=en üst, yüksek=alt
    parent_id          = Column(String(36), ForeignKey("org_titles.id"), nullable=True)
    budget_limit       = Column(Float, nullable=True)                  # None = limitsiz
    sort_order         = Column(Integer, default=0)
    pm_permission_level = Column(String(16), nullable=True)            # 'mudur' | 'yonetici' | 'asistan' | None

    parent   = relationship("OrgTitle", remote_side="OrgTitle.id", back_populates="children",
                            foreign_keys="OrgTitle.parent_id")
    children = relationship("OrgTitle", back_populates="parent",
                            foreign_keys="OrgTitle.parent_id")
    users    = relationship("User", back_populates="org_title")

    @property
    def budget_limit_display(self) -> str:
        if self.budget_limit is None:
            return "Limitsiz"
        return f"₺{self.budget_limit:,.0f}".replace(",", ".")


class EventType(Base):
    """DB-tabanlı etkinlik tipleri (admin tarafından yönetilir)"""
    __tablename__ = "event_types"
    id         = Column(String(36), primary_key=True, default=_uuid)
    code       = Column(String(10), unique=True, nullable=False)   # 'yi', 'yd', 'ut', 'tk', 'dk'
    label      = Column(String(100), nullable=False)
    active     = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "code":       self.code,
            "label":      self.label,
            "active":     self.active,
            "sort_order": self.sort_order,
        }


class User(Base):
    """Kullanıcı modeli — admin / mudur / yonetici / asistan / satinalma / muhasebe_muduru / muhasebe"""
    __tablename__ = "users"

    id           = Column(String(36), primary_key=True, default=_uuid)
    email        = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role         = Column(String(32), nullable=False, default="yonetici")
    name         = Column(String(100), nullable=False)
    surname      = Column(String(100), nullable=False)
    title        = Column(String(100), default="")
    phone        = Column(String(30), default="")
    avatar_b64   = Column(Text, default="")          # profil fotoğrafı base64 (data URI)
    active       = Column(Boolean, default=True, nullable=False)
    company_id   = Column(String(36), nullable=True, index=True)   # tenant (desk ile ortak DB)
    created_at   = Column(DateTime, default=_now, nullable=False)
    org_title_id = Column(String(36), ForeignKey("org_titles.id"), nullable=True)
    team_id      = Column(String(36), ForeignKey("teams.id"),     nullable=True)
    manager_id   = Column(String(36), ForeignKey("users.id"),     nullable=True)  # doğrudan yönetici

    # İlişkiler
    created_requests = relationship("Request", back_populates="creator", foreign_keys="Request.created_by")
    created_budgets  = relationship("Budget",  back_populates="creator", foreign_keys="Budget.created_by")
    org_title        = relationship("OrgTitle", back_populates="users")
    team             = relationship("Team", back_populates="members", foreign_keys="User.team_id")
    manager          = relationship("User", remote_side="User.id", back_populates="reports",
                                    foreign_keys="User.manager_id")
    reports          = relationship("User", back_populates="manager", foreign_keys="User.manager_id")

    @property
    def full_name(self) -> str:
        return f"{self.name} {self.surname}".strip()

    @property
    def pm_level(self) -> Optional[str]:
        """Proje tarafı yetki grubu. mudur/yonetici/asistan için anlamlı; diğer roller için None."""
        if self.role in ("mudur", "yonetici", "asistan"):
            return self.role
        return None

    @property
    def is_gm(self) -> bool:
        """Genel Müdür ve üstü mü? Kanonik ROLE_RANK ile (genel_mudur/admin/
        super_admin) — desk ile tek kaynaktan tutarlı."""
        from roles import has_role_min
        return has_role_min(self.role, "genel_mudur")

    @property
    def is_pm_side(self) -> bool:
        """Proje tarafı mı? (mudur/yonetici/asistan)"""
        return self.role in ("mudur", "yonetici", "asistan")

    @property
    def role_label(self) -> str:
        return USER_ROLE_LABELS.get(self.role, self.role)

    @property
    def initials(self) -> str:
        parts = [(self.name or "")[:1], (self.surname or "")[:1]]
        return "".join(p for p in parts if p).upper() or "?"

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "email":      self.email,
            "role":       self.role,
            "role_label": self.role_label,
            "name":       self.name,
            "surname":    self.surname,
            "full_name":  self.full_name,
            "title":      self.title,
            "phone":      self.phone,
            "active":     self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Vendor(Base):
    """Tedarikçi / Mekan modeli (Venue + FinancialVendor birleşimi)"""
    __tablename__ = "vendors"

    id           = Column(String(36), primary_key=True, default=_uuid)
    company_id   = Column(String(36), nullable=True, index=True)  # miceapp'te companies tablosu yok; sadece referans
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
    created_by   = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at   = Column(DateTime, default=_now, nullable=False)
    updated_at   = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    invoices     = relationship("Invoice", back_populates="vendor",
                               foreign_keys="Invoice.vendor_id")
    prepayments  = relationship("VendorPrepayment", back_populates="vendor",
                                order_by="VendorPrepayment.payment_date")

    @property
    def docs_list(self) -> list:
        try:
            return json.loads(self.docs_json or "[]")
        except Exception:
            return []

    @property
    def cities(self) -> list:
        try:
            return json.loads(self.cities_json or "[]")
        except Exception:
            return []

    @cities.setter
    def cities(self, value: list) -> None:
        self.cities_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def halls(self) -> list:
        try:
            return json.loads(self.halls_json or "[]")
        except Exception:
            return []

    @halls.setter
    def halls(self, value: list) -> None:
        self.halls_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def contacts(self) -> list:
        try:
            return json.loads(self.contacts_json or "[]")
        except Exception:
            return []

    @contacts.setter
    def contacts(self, value: list) -> None:
        self.contacts_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def supplier_type_label(self) -> str:
        for st in SUPPLIER_TYPES:
            if st["value"] == self.supplier_type:
                return st["label"]
        return self.supplier_type or ""

    @property
    def primary_contact(self):
        contacts = self.contacts
        return contacts[0] if contacts else None

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "name":           self.name,
            "city":           self.city,
            "cities":         self.cities,
            "supplier_type":  self.supplier_type,
            "address":        self.address,
            "phone":          self.phone,
            "email":          self.email,
            "stars":          self.stars,
            "total_rooms":    self.total_rooms,
            "halls":          self.halls,
            "contacts":       self.contacts,
            "payment_term":   self.payment_term,
            "website":        self.website,
            "tax_no":         self.tax_no,
            "tax_office":     self.tax_office,
            "iban":           self.iban,
            "active":         self.active,
        }


# Backward-compat aliases
Venue = Vendor


class Customer(Base):
    """Müşteri / Firma modeli"""
    __tablename__ = "customers"

    id                  = Column(String(36), primary_key=True, default=_uuid)
    company_id          = Column(String(36), nullable=True, index=True)
    owner_id            = Column(String(36), nullable=True, index=True)
    name                = Column(String(255), nullable=False)
    code                = Column(String(10), unique=True, nullable=False)
    sector              = Column(String(100), default="")
    address             = Column(Text, default="")
    tax_office          = Column(String(100), default="")
    tax_no              = Column(String(30), default="")
    email               = Column(String(255), default="")
    phone               = Column(String(30), default="")
    notes               = Column(Text, default="")
    contacts_json       = Column(Text, default="[]")
    payment_term        = Column(String(100), default="")
    payment_dow         = Column(Integer, nullable=True)
    docs_json           = Column(Text, default="[]")
    team_id             = Column(String(36), ForeignKey("teams.id"), nullable=True)
    created_at          = Column(DateTime, default=_now, nullable=False)
    excel_template_path = Column(String(500), default="")
    excel_template_b64  = Column(Text, default="")
    excel_config_json   = Column(Text, default="{}")
    active              = Column(Boolean, default=True, nullable=False)
    is_efatura_user     = Column(Boolean, nullable=True)
    efatura_alias       = Column(String(100), nullable=True)
    efatura_checked_at  = Column(DateTime, nullable=True)

    # İlişkiler
    requests = relationship("Request", back_populates="customer")
    team     = relationship("Team", foreign_keys="Customer.team_id")

    @property
    def contacts(self) -> list:
        try:
            return json.loads(self.contacts_json or "[]")
        except Exception:
            return []

    @contacts.setter
    def contacts(self, value: list) -> None:
        self.contacts_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def docs_list(self) -> list:
        try:
            return json.loads(self.docs_json or "[]")
        except Exception:
            return []

    @property
    def excel_config(self) -> dict:
        try:
            return json.loads(self.excel_config_json or "{}")
        except Exception:
            return {}

    @property
    def primary_contact(self):
        c = self.contacts
        return c[0] if c else None

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "name":       self.name,
            "code":       self.code,
            "sector":     self.sector,
            "address":    self.address,
            "tax_office": self.tax_office,
            "tax_number": self.tax_number,
            "email":      self.email,
            "phone":      self.phone,
            "notes":      self.notes,
            "contacts":   self.contacts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Request(Base):
    """Etkinlik Talebi modeli"""
    __tablename__ = "requests"

    id               = Column(String(36), primary_key=True, default=_uuid)
    company_id       = Column(String(36), nullable=True, index=True)   # tenant
    request_no       = Column(String(50), unique=True, nullable=False, index=True)
    client_name      = Column(String(255), nullable=False)
    customer_id      = Column(String(36), ForeignKey("customers.id"), nullable=True)
    event_name       = Column(String(255), nullable=False)
    event_type       = Column(String(32), default="toplanti")
    city             = Column(String(255), default="")
    cities_json      = Column(Text, default="[]")
    attendee_count   = Column(Integer, default=0)
    hekim_count      = Column(Integer, nullable=True)   # ut/yi tipi: hekim katılımcı sayısı
    staff_count      = Column(Integer, nullable=True)   # ut/yi tipi: staff katılımcı sayısı
    check_in         = Column(String(10), nullable=True)    # YYYY-MM-DD string
    check_out        = Column(String(10), nullable=True)
    accom_check_in   = Column(String(10), nullable=True)
    accom_check_out  = Column(String(10), nullable=True)
    quote_deadline   = Column(String(10), nullable=True)    # PM'in istediği teklif son tarihi
    status           = Column(String(32), default="draft", nullable=False)
    items_json       = Column(Text, default="{}")           # section → list[item] JSON
    description      = Column(Text, default="")
    notes            = Column(Text, default="")
    preferred_venues_json = Column(Text, default="[]")      # list[venue_id]
    selected_venues_json  = Column(Text, default="[]")      # list[venue_id]
    contact_person_json   = Column(Text, default="{}")      # selected contact info snapshot
    confirmed_at          = Column(DateTime, nullable=True)
    confirmed_budget_id   = Column(String(36), nullable=True)  # onaylanan bütçe id
    cancellation_reason   = Column(Text, default="")
    revision_count        = Column(Integer, default=0)
    is_funded             = Column(Boolean, default=False, nullable=False)   # fon/sponsor destekli mi
    funding_source        = Column(String(255), default="")                   # fon kaynağı (opsiyonel serbest metin)
    # Fon havuzu alanları (sadece is_fund_pool=True ise anlamlı)
    is_fund_pool              = Column(Boolean, default=False, nullable=False)
    fund_pool_type            = Column(String(16), default="customer")        # "customer" | "vendor"
    parent_fund_request_id    = Column(String(36), ForeignKey("requests.id"), nullable=True)
    fund_currency             = Column(String(3), default="TRY")
    fund_initial_amount       = Column(Float, default=0.0)                    # KDV dahil
    fund_initial_vat_rate     = Column(Float, default=20.0)                   # yüzde
    fund_vendor_name          = Column(String(255), default="")               # vendor pool için tedarikçi adı
    team_id          = Column(String(36), ForeignKey("teams.id"), nullable=True)
    created_by       = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at       = Column(DateTime, default=_now, nullable=False)
    updated_at       = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # İlişkiler
    customer = relationship("Customer", back_populates="requests")
    creator  = relationship("User", back_populates="created_requests", foreign_keys=[created_by])
    team     = relationship("Team", foreign_keys="Request.team_id")
    budgets              = relationship("Budget", back_populates="request", cascade="all, delete-orphan")
    invoices             = relationship("Invoice", back_populates="request", order_by="Invoice.invoice_date",
                                        cascade="all, delete-orphan")
    expense_reports      = relationship("ExpenseReport", back_populates="request",
                                        cascade="all, delete-orphan",
                                        order_by="ExpenseReport.created_at")
    undocumented_entries = relationship("UndocumentedEntry", back_populates="request",
                                        cascade="all, delete-orphan",
                                        order_by="UndocumentedEntry.entry_date")
    closure_request      = relationship("ClosureRequest", back_populates="request",
                                        uselist=False, cascade="all, delete-orphan")
    activity_logs        = relationship("ActivityLog", back_populates="request",
                                        cascade="all, delete-orphan",
                                        order_by="ActivityLog.created_at")
    req_notes            = relationship("RequestNote", back_populates="request",
                                        cascade="all, delete-orphan",
                                        order_by="RequestNote.created_at")
    documents            = relationship("RequestDocument", back_populates="request",
                                        cascade="all, delete-orphan",
                                        order_by="RequestDocument.created_at")

    @property
    def cities(self) -> list:
        try:
            return json.loads(self.cities_json or "[]")
        except Exception:
            return []

    @cities.setter
    def cities(self, value: list) -> None:
        self.cities_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def items(self) -> dict:
        try:
            return json.loads(self.items_json or "{}")
        except Exception:
            return {}

    @items.setter
    def items(self, value: dict) -> None:
        self.items_json = json.dumps(value or {}, ensure_ascii=False)

    @property
    def preferred_venues(self) -> list:
        try:
            return json.loads(self.preferred_venues_json or "[]")
        except Exception:
            return []

    @preferred_venues.setter
    def preferred_venues(self, value: list) -> None:
        self.preferred_venues_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def selected_venues(self) -> list:
        try:
            return json.loads(self.selected_venues_json or "[]")
        except Exception:
            return []

    @selected_venues.setter
    def selected_venues(self, value: list) -> None:
        self.selected_venues_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def contact_person(self) -> dict:
        try:
            return json.loads(self.contact_person_json or "{}")
        except Exception:
            return {}

    @property
    def status_label(self) -> str:
        return REQUEST_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        return REQUEST_STATUS_COLORS.get(self.status, "secondary")

    @property
    def event_type_label(self) -> str:
        # event_type now stores the code (yi/yd/ut/tk/dk) — label is looked up at runtime
        return self.event_type

    @property
    def cities_display(self) -> str:
        cities = self.cities
        if cities:
            return ", ".join(cities)
        return self.city or ""

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "request_no":       self.request_no,
            "client_name":      self.client_name,
            "customer_id":      self.customer_id,
            "event_name":       self.event_name,
            "event_type":       self.event_type,
            "event_type_label": self.event_type_label,
            "city":             self.city,
            "cities":           self.cities,
            "cities_display":   self.cities_display,
            "attendee_count":   self.attendee_count,
            "check_in":         self.check_in,
            "check_out":        self.check_out,
            "accom_check_in":   self.accom_check_in,
            "accom_check_out":  self.accom_check_out,
            "status":           self.status,
            "status_label":     self.status_label,
            "status_color":     self.status_color,
            "items":            self.items,
            "description":      self.description,
            "notes":            self.notes,
            "preferred_venues":  self.preferred_venues,
            "selected_venues":   self.selected_venues,
            "contact_person":    self.contact_person,
            "created_by":        self.created_by,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
        }


class RequestTemplate(Base):
    """Tekrar eden RFQ/talep şablonu — takım bazlı."""
    __tablename__ = "request_templates"

    id          = Column(String(36), primary_key=True, default=_uuid)
    name        = Column(String(200), nullable=False)
    description = Column(Text, default="")
    event_type  = Column(String(32), default="")         # önerilen etkinlik tipi
    items_json  = Column(Text, default="{}")             # Request.items_json ile aynı yapı
    team_id     = Column(String(36), ForeignKey("teams.id"), nullable=True)
    company_id  = Column(String(36), nullable=True, index=True)
    created_by  = Column(String(36), ForeignKey("users.id"), nullable=False)
    active      = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, default=_now, nullable=False)
    updated_at  = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    team    = relationship("Team",   foreign_keys=[team_id])
    creator = relationship("User",   foreign_keys=[created_by])

    @property
    def items(self) -> dict:
        try:
            return json.loads(self.items_json or "{}")
        except Exception:
            return {}


class FundTransfer(Base):
    """Fon havuzundan alt referansa yapılan iki yönlü transfer.

    direction:
      "out" → Fon havuzundan alt referansa (normal dağıtım, ref'in ciro'suna eklenir)
      "in"  → Alt referanstan fon havuzuna (iade, ref'in ciro'sundan düşer)

    Tutar KDV dahil ve fon currency cinsinden saklanır.
    """
    __tablename__ = "fund_transfers"

    id                 = Column(String(36), primary_key=True, default=_uuid)
    fund_request_id    = Column(String(36), ForeignKey("requests.id"), nullable=False)
    related_request_id = Column(String(36), ForeignKey("requests.id"), nullable=False)
    direction          = Column(String(10), nullable=False)   # "out" | "in"
    amount             = Column(Float, nullable=False)        # KDV dahil
    vat_rate           = Column(Float, default=20.0)          # yüzde
    currency           = Column(String(3), default="TRY")
    exchange_rate_try  = Column(Float, default=1.0)           # transfer anındaki TRY kuru
    description        = Column(Text, default="")
    transfer_date      = Column(String(10), nullable=False)   # YYYY-MM-DD
    created_by         = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at         = Column(DateTime, default=_now, nullable=False)

    fund_request    = relationship("Request", foreign_keys=[fund_request_id])
    related_request = relationship("Request", foreign_keys=[related_request_id])
    creator         = relationship("User", foreign_keys=[created_by])

    @property
    def amount_excl_vat(self) -> float:
        try:
            if self.vat_rate:
                return round(float(self.amount) / (1.0 + float(self.vat_rate) / 100.0), 2)
            return round(float(self.amount), 2)
        except Exception:
            return 0.0

    @property
    def amount_vat(self) -> float:
        return round(float(self.amount) - self.amount_excl_vat, 2)

    @property
    def amount_try(self) -> float:
        """TRY karşılığı (raporlar için)."""
        try:
            return round(float(self.amount) * float(self.exchange_rate_try or 1.0), 2)
        except Exception:
            return 0.0

    @property
    def amount_try_excl_vat(self) -> float:
        try:
            return round(self.amount_excl_vat * float(self.exchange_rate_try or 1.0), 2)
        except Exception:
            return 0.0


class Budget(Base):
    """Bütçe modeli"""
    __tablename__ = "budgets"

    id                   = Column(String(36), primary_key=True, default=_uuid)
    company_id           = Column(String(36), nullable=True, index=True)   # tenant
    request_id           = Column(String(36), ForeignKey("requests.id"), nullable=False)
    venue_name           = Column(String(255), default="")
    venue_id             = Column(String(36), nullable=True)   # Venue.id bağlantısı (isteğe bağlı)
    rows_json            = Column(Text, default="[]")     # list[BudgetRow] JSON
    created_by           = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at           = Column(DateTime, default=_now, nullable=False)
    updated_at           = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    budget_status        = Column(String(32), default="draft_satinalma", nullable=False)
    revision_notes       = Column(Text, default="")   # manager → Satın Alma notları
    manager_notes        = Column(Text, default="")   # manager iç notları
    service_fee_pct      = Column(Float, default=0.0) # manager girer
    offer_currency       = Column(String(3), default="TRY")   # teklif para birimi
    exchange_rates_json  = Column(Text, default="{}")          # {"EUR":40.5,"USD":35.0}
    price_history_json   = Column(Text, default="[]")          # fiyat revize geçmişi
    price_snapshots_json = Column(Text, default="[]")          # fiyat arşivi (tam satır kopyaları)
    budget_type           = Column(String(16), default="offer")  # 'offer' | 'statement'
    statement_status      = Column(String(20), nullable=True)    # None | 'sent' | 'customer_approved'
    statement_sent_at     = Column(DateTime, nullable=True)
    statement_approved_at = Column(DateTime, nullable=True)

    # İlişkiler
    request = relationship("Request", back_populates="budgets")
    creator = relationship("User",    back_populates="created_budgets", foreign_keys=[created_by])

    @property
    def rows(self) -> list:
        try:
            return json.loads(self.rows_json or "[]")
        except Exception:
            return []

    @rows.setter
    def rows(self, value: list) -> None:
        self.rows_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def exchange_rates(self) -> dict:
        try:
            return json.loads(self.exchange_rates_json or "{}")
        except Exception:
            return {}

    @property
    def price_history(self) -> list:
        try:
            return json.loads(self.price_history_json or "[]")
        except Exception:
            return []

    @property
    def price_snapshots(self) -> list:
        try:
            return json.loads(self.price_snapshots_json or "[]")
        except Exception:
            return []

    def rate_to_try(self, currency: str) -> float:
        """Verilen para biriminin TRY karşılığı (1 birim = X TRY)"""
        if not currency or currency == "TRY":
            return 1.0
        return float(self.exchange_rates.get(currency, 1.0) or 1.0)

    def amount_to_try(self, amount: float, currency: str) -> float:
        return amount * self.rate_to_try(currency)

    @property
    def grand_cost(self) -> float:
        """KDV dahil toplam maliyet — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            cost   = float(row.get("cost_price", 0) or 0)
            vat    = float(row.get("vat_rate", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            subtotal = self.amount_to_try(cost * qty * nights, cur)
            total += subtotal * (1 + vat / 100)
        return round(total, 2)

    @property
    def grand_sale(self) -> float:
        """KDV dahil toplam satış — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            sale   = float(row.get("sale_price", 0) or 0)
            vat    = float(row.get("vat_rate", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            subtotal = self.amount_to_try(sale * qty * nights, cur)
            total += subtotal * (1 + vat / 100)
        return round(total, 2)

    @property
    def grand_cost_excl_vat(self) -> float:
        """KDV hariç toplam maliyet — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            cost   = float(row.get("cost_price", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            total += self.amount_to_try(cost * qty * nights, cur)
        return round(total, 2)

    @property
    def grand_sale_excl_vat(self) -> float:
        """KDV hariç toplam satış — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            sale   = float(row.get("sale_price", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            total += self.amount_to_try(sale * qty * nights, cur)
        return round(total, 2)

    @property
    def grand_sale_offer(self) -> float:
        """KDV dahil toplam satış — offer_currency cinsinden"""
        oc = self.offer_currency or "TRY"
        if oc == "TRY":
            return self.grand_sale
        offer_rate = self.rate_to_try(oc)
        return round(self.grand_sale / offer_rate, 2) if offer_rate else self.grand_sale

    def to_dict(self) -> dict:
        return {
            "id":                  self.id,
            "request_id":          self.request_id,
            "venue_name":          self.venue_name,
            "rows":                self.rows,
            "grand_cost":          self.grand_cost,
            "grand_sale":          self.grand_sale,
            "grand_sale_offer":    self.grand_sale_offer,
            "offer_currency":      self.offer_currency or "TRY",
            "exchange_rates":      self.exchange_rates,
            "created_by":          self.created_by,
            "created_at":          self.created_at.isoformat() if self.created_at else None,
            "updated_at":          self.updated_at.isoformat() if self.updated_at else None,
        }


class Service(Base):
    """Hizmet Kataloğu"""
    __tablename__ = "services"

    id          = Column(String(36), primary_key=True, default=_uuid)
    category    = Column(String(64), nullable=False)
    name        = Column(String(255), nullable=False)
    unit        = Column(String(50), default="Adet")
    description = Column(Text, default="")
    active      = Column(Boolean, default=True, nullable=False)
    sort_order  = Column(Integer, default=0, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "category":    self.category,
            "name":        self.name,
            "unit":        self.unit,
            "description": self.description,
            "active":      self.active,
            "sort_order":  self.sort_order,
        }


class CustomCategory(Base):
    """Admin tarafından oluşturulan özel kategoriler"""
    __tablename__ = "custom_categories"

    id        = Column(String(36), primary_key=True, default=_uuid)
    name      = Column(String(100), nullable=False)
    icon      = Column(String(10), default="📋")
    bg_color  = Column(String(10), default="#e0f2fe")
    txt_color = Column(String(10), default="#0c4a6e")

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "name":      self.name,
            "icon":      self.icon,
            "bg_color":  self.bg_color,
            "txt_color": self.txt_color,
        }


class EmailTemplate(Base):
    """Admin tarafından yönetilen e-posta şablonları"""
    __tablename__ = "email_templates"

    id          = Column(String(36), primary_key=True, default=_uuid)
    slug        = Column(String(64), unique=True, nullable=False)   # rfq | confirm_venue | cancel_venue | ...
    name        = Column(String(200), nullable=False)
    description = Column(String(400), default="")
    subject_tpl = Column(String(400), nullable=False)               # {event_name}, {request_no}, ...
    body_tpl    = Column(Text, nullable=False)                       # plain text, {variable} placeholders
    active      = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, default=_now, nullable=False)
    updated_at  = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    def render(self, ctx: dict) -> tuple[str, str]:
        """subject, body döner — eksik key'lerde boş string"""
        class _Safe(dict):
            def __missing__(self, key):
                return f"{{{key}}}"
        safe = _Safe(ctx)
        return self.subject_tpl.format_map(safe), self.body_tpl.format_map(safe)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "slug":        self.slug,
            "name":        self.name,
            "description": self.description,
            "subject_tpl": self.subject_tpl,
            "body_tpl":    self.body_tpl,
            "active":      self.active,
        }


# E-posta şablonu değişken referansı (UI'da gösterilir)
EMAIL_TEMPLATE_VARS = [
    {"key": "event_name",      "label": "Etkinlik Adı"},
    {"key": "request_no",      "label": "Referans No"},
    {"key": "client_name",     "label": "Müşteri Adı"},
    {"key": "check_in",        "label": "Etkinlik Başlangıç Tarihi"},
    {"key": "check_out",       "label": "Etkinlik Bitiş Tarihi"},
    {"key": "accom_check_in",  "label": "Konaklama Giriş Tarihi"},
    {"key": "accom_check_out", "label": "Konaklama Çıkış Tarihi"},
    {"key": "attendee_count",  "label": "Katılımcı Sayısı"},
    {"key": "venue_name",      "label": "Mekan / Tedarikçi Adı"},
    {"key": "contact_name",    "label": "Kontak Kişi Adı"},
    {"key": "quote_deadline",  "label": "Teklif Son Tarihi"},
    {"key": "company_name",    "label": "Şirket Adı"},
    {"key": "company_email",   "label": "Şirket E-posta"},
    {"key": "company_phone",   "label": "Şirket Telefonu"},
    {"key": "email_signature", "label": "E-posta İmzası"},
]

# Varsayılan şablon içerikleri (seed için)
_EMAIL_TEMPLATE_DEFAULTS = [
    {
        "slug": "rfq",
        "name": "RFQ — Tedarikçiye Fiyat Teklifi Talebi",
        "description": "Tedarikçilere gönderilen fiyat teklifi talep e-postası konu satırı.",
        "subject_tpl": "{event_name} — Fiyat Teklifi Talebi / {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{client_name} adına organize ettiğimiz {event_name} etkinliği için fiyat teklifinizi talep etmekteyiz.\n\n"
            "Referans No : {request_no}\n"
            "Tarihler    : {check_in} – {check_out}\n"
            "Katılımcı   : {attendee_count} kişi\n\n"
            "Detaylı talep listesi aşağıda yer almaktadır. Son teklif tarihi: {quote_deadline}\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "confirm_venue",
        "name": "Konfirme Bildirimi — Seçilen Mekan",
        "description": "Müşteri onayı sonrasında seçilen venue'ya gönderilen konfirme e-postası.",
        "subject_tpl": "{event_name} — Konfirme Bildirimi / {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{event_name} etkinliğimiz için hazırladığınız teklif değerlendirmemiz tamamlanmış olup "
            "mekanınız / hizmetiniz konfirme edilmiştir.\n\n"
            "Referans No  : {request_no}\n"
            "Etkinlik     : {event_name}\n"
            "Müşteri      : {client_name}\n"
            "Tarihler     : {check_in} – {check_out}\n"
            "Katılımcı    : {attendee_count} kişi\n\n"
            "Kesin maliyet fiyatlarınızı en kısa sürede iletmenizi rica ederiz.\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "cancel_venue",
        "name": "İptal Bildirimi — Seçilmeyen Mekan",
        "description": "Konfirme veya iptal sonrasında seçilmeyen venue'lara gönderilen teşekkür / iptal e-postası.",
        "subject_tpl": "{event_name} — Teklif Talebi İptali / {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{event_name} etkinliğimiz kapsamında {venue_name} için tarafınıza ilettiğimiz "
            "teklif talebini iptal etmek durumunda kaldık.\n\n"
            "Referans No  : {request_no}\n"
            "Etkinlik     : {event_name}\n"
            "Tarihler     : {check_in} – {check_out}\n\n"
            "Gösterdiğiniz ilgi ve hazırladığınız teklif için teşekkür eder, "
            "ilerleyen projelerde tekrar bir araya gelmeyi umuyoruz.\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "offer_customer",
        "name": "Müşteriye Teklif Gönderimi",
        "description": "Müşteriye Excel teklif dosyası gönderilirken açılan e-posta şablonu.",
        "subject_tpl": "Etkinlik Teklifi: {event_name} — {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{event_name} etkinliğiniz için hazırlanan teklif dosyasını ekte sunmaktayız.\n\n"
            "Referans No: {request_no}\n"
            "Müşteri    : {client_name}\n"
            "Tarihler   : {check_in} – {check_out}\n\n"
            "Teklifi inceleyip dönüş yapmanızı rica ederiz.\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "budget_to_manager",
        "name": "Bütçe Hazır — Manager Bildirimi",
        "description": "Satın Alma bütçeyi manager'a gönderdiğinde oluşturulan bildirim e-postası.",
        "subject_tpl": "Yeni Bütçe Hazır: {request_no} — {event_name}",
        "body_tpl": (
            "Merhaba,\n\n"
            "{request_no} referans numaralı {event_name} talebi için bütçe hazırlanmıştır. "
            "İnceleyip fiyatlandırma yapmanızı rica ederiz.\n\n"
            "Müşteri  : {client_name}\n"
            "Tarihler : {check_in} – {check_out}\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "new_user_welcome",
        "name": "Yeni Kullanıcı — Hoşgeldin",
        "description": "Sisteme yeni eklenen kullanıcıya gönderilen hoşgeldin e-postası.",
        "subject_tpl": "{company_name} — Hesabınız Oluşturuldu",
        "body_tpl": (
            "Merhaba,\n\n"
            "{company_name} etkinlik yönetim sistemine hoş geldiniz. "
            "Hesabınız oluşturulmuştur.\n\n"
            "Sisteme giriş yaparak çalışmaya başlayabilirsiniz.\n\n"
            "{email_signature}"
        ),
    },
]


# FinancialVendor is merged into Vendor above — alias for backward compatibility
FinancialVendor = Vendor


PREPAYMENT_STATUSES = {
    "open":      ("Açık",       "warning"),
    "partial":   ("Kısmen Uygulandı", "info"),
    "applied":   ("Uygulandı",  "success"),
    "cancelled": ("İptal",      "secondary"),
}


class VendorPrepayment(Base):
    """Tedarikçiye yapılan ön ödeme / avans kaydı"""
    __tablename__ = "vendor_prepayments"

    id             = Column(String(36), primary_key=True, default=_uuid)
    company_id     = Column(String(36), nullable=True, index=True)   # tenant
    vendor_id      = Column(String(36), ForeignKey("vendors.id"), nullable=False, index=True)
    request_id     = Column(String(36), ForeignKey("requests.id"), nullable=True, index=True)
    amount         = Column(Float, default=0.0)           # ön ödeme tutarı
    applied_amount = Column(Float, default=0.0)           # faturaya uygulanan kısım
    payment_date   = Column(String(10), nullable=False)   # YYYY-MM-DD
    payment_method = Column(String(20), default="banka")  # banka|kredi_karti|cek
    notes          = Column(Text, default="")
    status         = Column(String(16), default="open")   # open|partial|applied|cancelled
    created_by     = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at     = Column(DateTime, default=_now, nullable=False)
    updated_at     = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    vendor  = relationship("Vendor", back_populates="prepayments")
    request = relationship("Request", foreign_keys=[request_id])
    creator = relationship("User",   foreign_keys=[created_by])

    @property
    def remaining(self) -> float:
        return round(max(0.0, (self.amount or 0) - (self.applied_amount or 0)), 2)


class Invoice(Base):
    """Fatura modeli — kesilen/gelen/komisyon/iade"""
    __tablename__ = "invoices"

    id            = Column(String(36), primary_key=True, default=_uuid)
    company_id    = Column(String(36), nullable=True, index=True)   # tenant
    request_id    = Column(String(36), ForeignKey("requests.id"), nullable=True, index=True)
    vendor_id     = Column(String(36), ForeignKey("vendors.id"), nullable=True, index=True)
    invoice_type  = Column(String(32), nullable=False)   # kesilen|gelen|komisyon|iade_kesilen|iade_gelen
    invoice_no    = Column(String(100), default="")
    invoice_date  = Column(String(10), nullable=False)   # YYYY-MM-DD string
    due_date      = Column(String(10), nullable=True)    # YYYY-MM-DD string
    currency      = Column(String(10), default="TRY", nullable=False)
    vendor_name   = Column(String(255), default="")      # tedarikçi/müşteri adı (serbest metin — geriye uyumluluk)
    description   = Column(Text, default="")
    amount        = Column(Float, default=0.0)           # KDV hariç toplam, TRY (lines'dan hesaplanır)
    vat_rate      = Column(Float, default=20.0)          # geriye uyumluluk için (artık lines'da)
    vat_amount    = Column(Float, default=0.0)           # KDV tutarı toplamı
    total_amount  = Column(Float, default=0.0)           # KDV dahil toplam
    lines_json    = Column(Text, default="[]")           # list[{description, amount, vat_rate, vat_amount}]
    document_path    = Column(String(500), nullable=True)   # disk path (relative)
    document_name    = Column(String(255), nullable=True)   # orijinal dosya adı
    status           = Column(String(20), default="pending") # pending|mudur_approved|gm_approved|approved|rejected|cancelled
    payment_status   = Column(String(20), default="unpaid")   # unpaid|paid|partial
    paid_at          = Column(String(10), nullable=True)       # YYYY-MM-DD (son ödeme tarihi)
    paid_amount      = Column(Float, default=0.0)              # birikimli ödenen tutar
    payment_method   = Column(String(20), default="banka")     # banka|kredi_karti|cek
    cc_due_date      = Column(String(10), nullable=True)       # kredi kartı son ödeme tarihi (YYYY-MM-DD)
    cc_pending_amount= Column(Float, default=0.0)              # kartla taahhüt edilen ama henüz bankadan çıkmayan tutar
    rejection_note       = Column(String(300), default="")
    notes                = Column(Text, nullable=True)   # micedesk uyumu
    approved_by          = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at          = Column(DateTime, nullable=True)
    current_approver_id  = Column(String(36), ForeignKey("users.id"), nullable=True)
    # Fatura bölme — parent fatura birden fazla alt referansa pay edildiğinde
    is_split_parent      = Column(Boolean, default=False, nullable=False)
    parent_invoice_id    = Column(String(36), ForeignKey("invoices.id"), nullable=True)
    created_by           = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at           = Column(DateTime, default=_now, nullable=False)
    updated_at           = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    # micedesk köprü alanları (micedesk'in yazdığı faturalar için)
    ref_id               = Column(String(36), nullable=True)   # micedesk references.id
    source_invoice_id    = Column(String(36), nullable=True)   # komisyon: ana tedarikçi faturası
    # Desk muhasebe-kesim köprüsü: event onayı biten komisyon "onay_bekliyor"a çekilir,
    # Zehra desk'te (approval_status='onay_bekliyor' + current_approver_id IS NULL) keser.
    approval_status      = Column(String(20), nullable=True)   # desk: onay_bekliyor | approved | reddedildi
    coordinator_status   = Column(String(20), nullable=True)   # beklemede | onaylandi | reddedildi
    coordinator_note     = Column(Text, nullable=True)
    coordinator_reviewed_at = Column(DateTime, nullable=True)
    coordinator_reviewed_by = Column(String(36), nullable=True)

    request          = relationship("Request", back_populates="invoices")
    vendor           = relationship("Vendor", back_populates="invoices", foreign_keys=[vendor_id])
    creator          = relationship("User", foreign_keys=[created_by])
    approver         = relationship("User", foreign_keys=[approved_by])
    current_approver = relationship("User", foreign_keys=[current_approver_id])
    logs             = relationship("InvoiceLog", back_populates="invoice")

    @property
    def lines(self) -> list:
        try:
            return json.loads(self.lines_json or "[]")
        except Exception:
            return []

    @property
    def type_label(self) -> str:
        return INVOICE_TYPE_LABELS.get(self.invoice_type, self.invoice_type)

    @property
    def is_income(self) -> bool:
        """Gelir etkisi pozitif mi? kesilen + komisyon = gelir; iade_gelen = maliyet azaltır"""
        return self.invoice_type in ("kesilen", "iade_gelen", "komisyon")

    @property
    def is_cost(self) -> bool:
        """Maliyet etkisi var mı? komisyon maliyet değil, gelirdir."""
        return self.invoice_type in ("gelen", "iade_kesilen")

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "request_id":    self.request_id,
            "invoice_type":  self.invoice_type,
            "type_label":    self.type_label,
            "invoice_no":    self.invoice_no,
            "invoice_date":  self.invoice_date.isoformat() if hasattr(self.invoice_date, "isoformat") else self.invoice_date,
            "due_date":      self.due_date.isoformat() if hasattr(self.due_date, "isoformat") else self.due_date,
            "currency":      self.currency or "TRY",
            "vendor_name":   self.vendor_name,
            "description":   self.description,
            "amount":        self.amount,
            "vat_rate":      self.vat_rate,
            "vat_amount":    self.vat_amount,
            "total_amount":  self.total_amount,
            "lines":         self.lines,
            "document_path": self.document_path,
            "document_name": self.document_name,
            "status":        self.status,
            "created_by":    self.created_by,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# InvoiceLog — Fatura işlem geçmişi
# ---------------------------------------------------------------------------

INVOICE_LOG_ACTIONS = {
    "created":   ("Oluşturuldu",             "secondary", "bi-plus-circle"),
    "cut":       ("Fatura Kesildi",          "info",      "bi-scissors"),
    "submitted": ("Onaya Gönderildi",        "warning",   "bi-send"),
    "approved":  ("Onaylandı",               "success",   "bi-check-circle"),
    "forwarded": ("Üst Onaya Yönlendirildi", "primary",   "bi-arrow-up-circle"),
    "rejected":  ("Reddedildi",              "danger",    "bi-x-circle"),
    "payment":   ("Ödeme Yapıldı",           "success",   "bi-cash-stack"),
    "edited":    ("Düzenlendi",              "secondary", "bi-pencil"),
    "reassigned":("Referans Atandı",         "info",      "bi-link"),
}


# ---------------------------------------------------------------------------
# Ön Ödeme Talep Sistemi
# ---------------------------------------------------------------------------

PREPAYMENT_REQUEST_STATUSES = {
    "pending_gm":  ("GM Onayı Bekliyor",   "warning",  "bi-hourglass-split"),
    "approved":    ("Muhasebe Bekliyor",   "info",     "bi-check-circle"),
    "paid":        ("Ödendi",             "success",  "bi-check2-all"),
    "rejected":    ("Reddedildi",         "danger",   "bi-x-circle"),
    "cancelled":   ("İptal Edildi",       "secondary","bi-slash-circle"),
}

PREPAYMENT_REQUEST_LOG_ACTIONS = {
    "created":    ("Oluşturuldu",        "#64748b",  "bi-plus-circle"),
    "approved":   ("GM Onayladı",        "#16a34a",  "bi-check-circle-fill"),
    "rejected":   ("Reddedildi",         "#dc2626",  "bi-x-circle-fill"),
    "paid":       ("Ödeme Yapıldı",      "#2563eb",  "bi-bank"),
    "cancelled":  ("İptal Edildi",       "#64748b",  "bi-slash-circle"),
    "note":       ("Not Eklendi",        "#7c3aed",  "bi-chat-left-text"),
}


class PrepaymentRequest(Base):
    """PM / Müdür tarafından oluşturulan ön ödeme talebi — GM onayı → Muhasebe öder"""
    __tablename__ = "prepayment_requests"

    id             = Column(String(36), primary_key=True, default=_uuid)
    company_id     = Column(String(36), nullable=True, index=True)   # tenant (desk muhasebe için)
    vendor_id      = Column(String(36), ForeignKey("vendors.id"), nullable=False, index=True)
    request_id     = Column(String(36), ForeignKey("requests.id"), nullable=True, index=True)
    amount         = Column(Float, nullable=False)
    needed_date    = Column(String(10), nullable=True)              # ödeme/ihtiyaç tarihi YYYY-MM-DD
    description    = Column(Text, default="")
    notes          = Column(Text, default="")
    document_path  = Column(String(500), nullable=True)            # ek dosya (R2 key)
    document_name  = Column(String(255), nullable=True)

    # Durum akışı: pending_gm → approved → paid  (veya rejected / cancelled)
    status         = Column(String(20), default="pending_gm", nullable=False)

    # Talep eden
    requested_by   = Column(String(36), ForeignKey("users.id"), nullable=False)
    requested_at   = Column(DateTime, default=_now, nullable=False)

    # GM onayı
    approved_by    = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at    = Column(DateTime, nullable=True)
    approval_note  = Column(String(500), default="")   # GM'in muhasebeye notu
    rejection_note = Column(String(500), default="")

    # Muhasebe ödemesi
    paid_by        = Column(String(36), ForeignKey("users.id"), nullable=True)
    paid_at        = Column(String(10), nullable=True)          # YYYY-MM-DD
    payment_method = Column(String(20), nullable=True)          # banka|kredi_karti|cek
    cc_due_date    = Column(String(10), nullable=True)          # KK son ödeme tarihi
    vendor_prepayment_id = Column(String(36), ForeignKey("vendor_prepayments.id"), nullable=True)

    created_at     = Column(DateTime, default=_now, nullable=False)
    updated_at     = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    vendor            = relationship("Vendor", foreign_keys=[vendor_id])
    request           = relationship("Request", foreign_keys=[request_id])
    requester         = relationship("User", foreign_keys=[requested_by])
    approver          = relationship("User", foreign_keys=[approved_by])
    payer             = relationship("User", foreign_keys=[paid_by])
    vendor_prepayment = relationship("VendorPrepayment", foreign_keys=[vendor_prepayment_id])
    logs              = relationship("PrepaymentRequestLog", back_populates="prepayment_request")

    @property
    def status_label(self) -> str:
        return PREPAYMENT_REQUEST_STATUSES.get(self.status, (self.status,))[0]

    @property
    def status_color(self) -> str:
        return PREPAYMENT_REQUEST_STATUSES.get(self.status, ("", "secondary"))[1]


class PrepaymentRequestLog(Base):
    """Ön ödeme talebi üzerindeki her işlemin kaydı."""
    __tablename__ = "prepayment_request_logs"

    id                    = Column(String(36), primary_key=True, default=_uuid)
    prepayment_request_id = Column(String(36), ForeignKey("prepayment_requests.id"),
                                   nullable=False, index=True)
    action     = Column(String(32), nullable=False)
    actor_id   = Column(String(36), ForeignKey("users.id"), nullable=True)
    note       = Column(Text, default="")
    created_at = Column(DateTime, default=_now, nullable=False)

    prepayment_request = relationship("PrepaymentRequest", back_populates="logs")
    actor              = relationship("User", foreign_keys=[actor_id])


class InvoiceLog(Base):
    """Fatura üzerinde yapılan her işlemin kaydı."""
    __tablename__ = "invoice_logs"

    id             = Column(String(36), primary_key=True, default=_uuid)
    invoice_id     = Column(String(36), ForeignKey("invoices.id"), nullable=False, index=True)
    action         = Column(String(32), nullable=False)     # bkz. INVOICE_LOG_ACTIONS
    actor_id       = Column(String(36), ForeignKey("users.id"), nullable=True)
    amount         = Column(Float, nullable=True)           # ödeme tutarı (ödeme logunda)
    payment_method = Column(String(20), nullable=True)      # banka|kredi_karti|cek
    cc_due_date    = Column(String(10), nullable=True)      # KK son ödeme tarihi
    note           = Column(Text, default="")
    created_at     = Column(DateTime, default=_now, nullable=False)

    invoice = relationship("Invoice", back_populates="logs")
    actor   = relationship("User", foreign_keys=[actor_id])


# ---------------------------------------------------------------------------
# HBF — Harcama Bildirim Formu
# ---------------------------------------------------------------------------

EXPENSE_PAYMENT_METHODS = [
    {"value": "kredi_karti", "label": "Kredi Kartı"},
    {"value": "nakit",       "label": "Nakit"},
]

EXPENSE_DOC_TYPES = [
    {"value": "fatura",    "label": "Fatura"},
    {"value": "fis",       "label": "Fiş"},
    {"value": "belgesiz",  "label": "Belgesiz"},
]

# HBF onay zinciri (event+desk ortak):
#   draft → submitted(müdür onayında) → mudur_onayladi(GM onayında)
#         → onaylandi(muhasebe bekliyor) → kapandi(muhasebe ödedi/kapattı)
#   rejected: her aşamada mümkün
EXPENSE_STATUSES = [
    {"value": "draft",          "label": "Taslak",          "color": "secondary"},
    {"value": "owner_onayi",    "label": "Dosya Sahibi Onayında", "color": "warning"},
    {"value": "submitted",      "label": "Müdür Onayında",  "color": "warning"},
    {"value": "mudur_onayladi", "label": "GM Onayında",     "color": "info"},
    {"value": "onaylandi",      "label": "Muhasebe Bekliyor","color": "primary"},
    {"value": "kapandi",        "label": "Kapandı",         "color": "success"},
    {"value": "rejected",       "label": "Reddedildi",      "color": "danger"},
]
EXPENSE_STATUS_LABELS = {s["value"]: s["label"] for s in EXPENSE_STATUSES}
EXPENSE_STATUS_COLORS = {s["value"]: s["color"] for s in EXPENSE_STATUSES}
# Geriye dönük: eski "approved" kayıtları "onaylandi" gibi gösterilir (filtre listesinde yok)
EXPENSE_STATUS_LABELS["approved"] = "Onaylandı"
EXPENSE_STATUS_COLORS["approved"] = "success"


class ExpenseReport(Base):
    """HBF — Harcama Bildirim Formu başlığı"""
    __tablename__ = "expense_reports"

    id               = Column(String(36), primary_key=True, default=_uuid)
    company_id       = Column(String(36), nullable=True, index=True)  # tenant (desk izolasyonu için)
    request_id       = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    request_ids_json = Column(Text, default="[]")   # JSON array of {id,request_no,event_name,client_name}
    title            = Column(String(300), default="")
    status           = Column(String(16), default="draft")   # bkz. EXPENSE_STATUSES
    submitted_by     = Column(String(36), ForeignKey("users.id"), nullable=False)
    # Dosya sahibi onayı (0. aşama — gönderen ≠ referans sahibi ise)
    owner_approved_by = Column(String(36), nullable=True)
    owner_approved_at = Column(DateTime, nullable=True)
    # Müdür onayı (1. aşama)
    manager_approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    manager_approved_at = Column(DateTime, nullable=True)
    # GM onayı (2. aşama) — mevcut approved_by/at GM'i temsil eder
    approved_by      = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at      = Column(DateTime, nullable=True)
    rejection_note   = Column(Text, default="")
    # Muhasebe ödeme/kapatma (3. aşama) — desk tarafında doldurulur
    paid_by            = Column(String(36), ForeignKey("users.id"), nullable=True)
    paid_at            = Column(DateTime, nullable=True)
    payment_method     = Column(String(20), nullable=True)   # nakit | banka
    bank_account_id    = Column(String(36), nullable=True)
    cash_book_id       = Column(String(36), nullable=True)
    general_expense_id = Column(String(36), nullable=True)   # oluşan GeneralExpense kaydı
    created_at       = Column(DateTime, default=_now, nullable=False)
    updated_at       = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # İlişkiler
    request   = relationship("Request",  back_populates="expense_reports")
    submitter = relationship("User",  foreign_keys=[submitted_by])
    approver  = relationship("User",  foreign_keys=[approved_by])
    items     = relationship("ExpenseItem", back_populates="report",
                             cascade="all, delete-orphan",
                             order_by="ExpenseItem.item_date")

    @property
    def status_label(self) -> str:
        return EXPENSE_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        return EXPENSE_STATUS_COLORS.get(self.status, "secondary")

    @property
    def grand_total(self) -> float:
        return round(sum(i.total_amount for i in self.items), 2)

    @property
    def grand_excl_vat(self) -> float:
        return round(sum(i.amount for i in self.items), 2)

    @property
    def grand_vat(self) -> float:
        return round(sum(i.vat_amount for i in self.items), 2)


class ExpenseItem(Base):
    """HBF kalemi"""
    __tablename__ = "expense_items"

    id                  = Column(String(36), primary_key=True, default=_uuid)
    report_id           = Column(String(36), ForeignKey("expense_reports.id"), nullable=False, index=True)
    assigned_request_id = Column(String(36), ForeignKey("requests.id"), nullable=True)  # hangi ref'e atandı
    item_date           = Column(String(10), default="")    # YYYY-MM-DD
    description         = Column(String(300), default="")
    payment_method      = Column(String(16), default="nakit")   # kredi_karti | nakit
    credit_card_id      = Column(String(36), nullable=True)     # kredi_karti ise: micedesk credit_cards.id
    document_type       = Column(String(16), default="fis")     # fatura | fis | belgesiz
    amount              = Column(Float, default=0.0)    # KDV hariç
    vat_rate            = Column(Float, default=0.0)    # 0 için belgesiz; 10, 20 vb.
    vat_amount          = Column(Float, default=0.0)
    total_amount        = Column(Float, default=0.0)    # KDV dahil
    document_path       = Column(String(500), nullable=True)
    document_name       = Column(String(255), nullable=True)
    sort_order          = Column(Integer, default=0)
    created_at          = Column(DateTime, default=_now, nullable=False)

    report = relationship("ExpenseReport", back_populates="items")

    @property
    def payment_label(self) -> str:
        return {"kredi_karti": "Kredi Kartı", "nakit": "Nakit"}.get(self.payment_method, self.payment_method)

    @property
    def doc_label(self) -> str:
        return {"fatura": "Fatura", "fis": "Fiş", "belgesiz": "Belgesiz"}.get(self.document_type, self.document_type)


# ---------------------------------------------------------------------------
# Belgesiz Gelir / Gider
# ---------------------------------------------------------------------------

class UndocumentedEntry(Base):
    """Belgesiz gelir veya gider kalemi (KDV'siz)"""
    __tablename__ = "undocumented_entries"

    id          = Column(String(36), primary_key=True, default=_uuid)
    request_id  = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    entry_type  = Column(String(8), nullable=False)    # gelir | gider
    description = Column(String(300), default="")
    amount      = Column(Float, default=0.0)           # KDV yoktur
    entry_date  = Column(String(10), default="")       # YYYY-MM-DD
    created_by  = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at  = Column(DateTime, default=_now, nullable=False)

    request = relationship("Request", back_populates="undocumented_entries")
    creator = relationship("User", foreign_keys=[created_by])


class Notification(Base):
    """Kullanıcı bildirimleri — bekleyen görevler için"""
    __tablename__ = "notifications"

    id         = Column(String(36), primary_key=True, default=_uuid)
    user_id    = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    notif_type = Column(String(50), nullable=False)
    # invoice_pending | hbf_submitted | budget_pricing | budget_revision | new_request
    title      = Column(String(200), nullable=False)
    message    = Column(String(500), default="")
    link       = Column(String(500), default="")
    ref_id     = Column(String(36), default="")   # ilgili nesnenin ID'si
    read_at    = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id])


class Settings(Base):
    """Sistem ayarları — tek satır (id=1)"""
    __tablename__ = "settings"

    id              = Column(Integer, primary_key=True, default=1)
    company_name    = Column(String(200), default="miceapp")
    company_address = Column(Text, default="")
    company_phone   = Column(String(50), default="")
    company_email   = Column(String(200), default="")
    logo_url        = Column(String(500), default="")
    email_signature = Column(Text, default="")
    rfq_subject_tpl = Column(String(300),
                             default="{event_name} Fiyat Teklifi - {request_no}")
    currency        = Column(String(10), default="₺")
    invoice_mudur_limit = Column(Float, nullable=True)   # None = her zaman GM onayı gerekli
    updated_at      = Column(DateTime, default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "company_name":    self.company_name,
            "company_address": self.company_address,
            "company_phone":   self.company_phone,
            "company_email":   self.company_email,
            "logo_url":        self.logo_url,
            "email_signature": self.email_signature,
            "rfq_subject_tpl": self.rfq_subject_tpl,
            "currency":        self.currency,
        }


# ---------------------------------------------------------------------------
# Dosya Kapama Onay Süreci
# ---------------------------------------------------------------------------

CLOSURE_STATUS_LABELS = {
    "pending_manager":  "Müdür Onayı Bekliyor",
    "pending_gm":       "Genel Müdür Onayı Bekliyor",
    "pending_finance":  "Muhasebe Müdürü Onayı Bekliyor",
    "closed":           "Kapatıldı",
    "rejected":         "Reddedildi",
}
CLOSURE_STATUS_COLORS = {
    "pending_manager":  "warning",
    "pending_gm":       "purple",
    "pending_finance":  "info",
    "closed":           "dark",
    "rejected":         "danger",
}


class ClosureRequest(Base):
    """Dosya kapama onay talebi — referans başına en fazla bir aktif kayıt."""
    __tablename__ = "closure_requests"

    id          = Column(String(36), primary_key=True, default=_uuid)
    request_id  = Column(String(36), ForeignKey("requests.id"), nullable=False, unique=True, index=True)

    # Gönderen (PM / referans sahibi)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    submitted_at = Column(DateTime, default=_now, nullable=False)
    note         = Column(Text, default="")  # PM notu

    # Adım 1 — Yönetici/Admin onayı
    l1_approver_id  = Column(String(36), ForeignKey("users.id"), nullable=True)
    l1_approved_at  = Column(DateTime, nullable=True)
    l1_note         = Column(Text, default="")

    # Adım 2 — Genel Müdür onayı (isteğe bağlı — tutar limit aşıyorsa)
    needs_gm        = Column(Boolean, default=False, nullable=False)
    gm_approver_id  = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_approved_at  = Column(DateTime, nullable=True)
    gm_note         = Column(Text, default="")

    # Adım 3 — Muhasebe Müdürü final onayı
    l2_approver_id  = Column(String(36), ForeignKey("users.id"), nullable=True)
    l2_approved_at  = Column(DateTime, nullable=True)
    l2_note         = Column(Text, default="")

    # Ret notu (herhangi bir adımdan)
    rejection_note  = Column(Text, default="")
    rejected_by_id  = Column(String(36), ForeignKey("users.id"), nullable=True)
    rejected_at     = Column(DateTime, nullable=True)

    # pending_manager | pending_gm | pending_finance | closed | rejected
    status      = Column(String(24), default="pending_manager", nullable=False)
    created_at  = Column(DateTime, default=_now, nullable=False)
    updated_at  = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # İlişkiler
    request     = relationship("Request", back_populates="closure_request")
    submitter   = relationship("User", foreign_keys=[submitted_by])
    l1_approver = relationship("User", foreign_keys=[l1_approver_id])
    gm_approver = relationship("User", foreign_keys=[gm_approver_id])
    l2_approver = relationship("User", foreign_keys=[l2_approver_id])
    rejected_by = relationship("User", foreign_keys=[rejected_by_id])

    @property
    def status_label(self) -> str:
        return CLOSURE_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        return CLOSURE_STATUS_COLORS.get(self.status, "secondary")


# ---------------------------------------------------------------------------
# Kütüphane — Notlar, Belgeler, Aktivite Logu
# ---------------------------------------------------------------------------

ACTIVITY_EVENT_ICONS = {
    "status_change":    "bi-arrow-right-circle",
    "note_added":       "bi-chat-left-text",
    "document_added":   "bi-paperclip",
    "document_removed": "bi-trash",
    "budget_created":   "bi-calculator",
    "budget_submitted": "bi-send",
    "budget_approved":  "bi-check-circle",
    "budget_rejected":  "bi-x-circle",
    "invoice_created":  "bi-receipt",
    "invoice_approved": "bi-receipt-cutoff",
    "invoice_rejected": "bi-x-circle",
    "closure_submitted":"bi-flag",
    "closure_approved": "bi-folder-check",
    "closure_rejected": "bi-folder-x",
    "request_created":  "bi-plus-circle",
}

ACTIVITY_EVENT_COLORS = {
    "status_change":    "primary",
    "note_added":       "secondary",
    "document_added":   "info",
    "document_removed": "danger",
    "budget_created":   "info",
    "budget_submitted": "warning",
    "budget_approved":  "success",
    "budget_rejected":  "danger",
    "invoice_created":  "info",
    "invoice_approved": "success",
    "invoice_rejected": "danger",
    "closure_submitted":"warning",
    "closure_approved": "success",
    "closure_rejected": "danger",
    "request_created":  "primary",
}

REQUEST_DOCUMENT_TYPES = [
    {"value": "teklif",   "label": "Teklif"},
    {"value": "sozlesme", "label": "Sözleşme"},
    {"value": "fatura",   "label": "Fatura"},
    {"value": "sunum",    "label": "Sunum"},
    {"value": "diger",    "label": "Diğer"},
]
REQUEST_DOCUMENT_TYPE_LABELS = {d["value"]: d["label"] for d in REQUEST_DOCUMENT_TYPES}


class ActivityLog(Base):
    """Referans aktivite logu — otomatik ve manuel kayıtlar"""
    __tablename__ = "activity_logs"

    id          = Column(String(36), primary_key=True, default=_uuid)
    request_id  = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    user_id     = Column(String(36), ForeignKey("users.id"), nullable=True)
    event_type  = Column(String(50), nullable=False)   # status_change | note_added | ...
    title       = Column(String(300), nullable=False)
    detail      = Column(Text, default="")
    created_at  = Column(DateTime, default=_now, nullable=False)

    request = relationship("Request", back_populates="activity_logs")
    user    = relationship("User", foreign_keys=[user_id])

    @property
    def icon(self) -> str:
        return ACTIVITY_EVENT_ICONS.get(self.event_type, "bi-circle")

    @property
    def color(self) -> str:
        return ACTIVITY_EVENT_COLORS.get(self.event_type, "secondary")


class RequestNote(Base):
    """Referans iç notu — yazışma, karar, gözlem"""
    __tablename__ = "request_notes"

    id          = Column(String(36), primary_key=True, default=_uuid)
    request_id  = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    created_by  = Column(String(36), ForeignKey("users.id"), nullable=False)
    content     = Column(Text, nullable=False)
    is_pinned   = Column(Boolean, default=False, nullable=False)
    created_at  = Column(DateTime, default=_now, nullable=False)
    updated_at  = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    request = relationship("Request", back_populates="req_notes")
    creator = relationship("User", foreign_keys=[created_by])


class RequestDocument(Base):
    """Referansa eklenen belge — teklif, sözleşme, sunum vb."""
    __tablename__ = "request_documents"

    id          = Column(String(36), primary_key=True, default=_uuid)
    request_id  = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    doc_type    = Column(String(20), default="diger")   # teklif|sozlesme|fatura|sunum|diger
    doc_name    = Column(String(255), nullable=False)   # kullanıcının verdiği isim
    file_path   = Column(String(500), nullable=False)   # static/ altında relative path
    file_name   = Column(String(255), nullable=False)   # orijinal dosya adı
    file_size   = Column(Integer, default=0)            # byte
    created_at  = Column(DateTime, default=_now, nullable=False)

    request  = relationship("Request", back_populates="documents")
    uploader = relationship("User", foreign_keys=[uploaded_by])

    @property
    def type_label(self) -> str:
        return REQUEST_DOCUMENT_TYPE_LABELS.get(self.doc_type, self.doc_type)

    @property
    def size_display(self) -> str:
        s = self.file_size or 0
        if s < 1024:
            return f"{s} B"
        elif s < 1024 * 1024:
            return f"{s // 1024} KB"
        else:
            return f"{s / (1024*1024):.1f} MB"


# ---------------------------------------------------------------------------
# Operasyon Ajanı Modülü — referansa bağlı aktif modüller
# ---------------------------------------------------------------------------
class RequestModule(Base):
    """Bir referansa bağlanan Operasyon Ajanı modülü."""
    __tablename__ = "request_modules"

    id               = Column(String(36), primary_key=True, default=_uuid)
    request_id       = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    module_type      = Column(String(32), default="operasyon")   # gelecekte başka modüller
    activated_by     = Column(String(36), ForeignKey("users.id"), nullable=True)
    activated_at     = Column(DateTime, default=_now)

    # Operasyon Ajanı tarafından dönen bilgiler
    oa_event_id             = Column(String(36))
    oa_manager_url          = Column(String(500))
    oa_coordinator_url      = Column(String(500))
    oa_transfer_supplier_url      = Column(String(500))
    oa_accommodation_supplier_url = Column(String(500))
    oa_task_supplier_url    = Column(String(500))   # Teknik/Dekor/Diğer tedarikçi görev portalı
    oa_client_url           = Column(String(500))   # Müşteri / salt-okunur etkinlik portalı

    active = Column(Boolean, default=True)

    request   = relationship("Request")
    activator = relationship("User", foreign_keys=[activated_by])


# ---------------------------------------------------------------------------
# Rol İzin Sistemi
# ---------------------------------------------------------------------------

PERMISSIONS = [
    {"key": "request_create",  "label": "Talep Oluştur",          "group": "Talepler"},
    {"key": "budget_view",     "label": "Bütçe Görüntüle",        "group": "Bütçeler"},
    {"key": "budget_edit",     "label": "Bütçe Düzenle / Oluştur","group": "Bütçeler"},
    {"key": "invoice_manage",  "label": "Fatura Yönet",           "group": "Finans"},
    {"key": "report_view",     "label": "Rapor Görüntüle",        "group": "Finans"},
    {"key": "venue_edit",      "label": "Tedarikçi Ekle / Düzenle","group": "Katalog"},
]

# Varsayılan rol izinleri (seed için)
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin":           ["request_create", "budget_view", "budget_edit", "invoice_manage", "report_view", "venue_edit"],
    "mudur":           ["request_create", "budget_view", "report_view"],
    "yonetici":        ["request_create", "budget_view"],
    "asistan":         ["request_create", "budget_view"],
    "satinalma":           ["budget_edit", "invoice_manage", "venue_edit"],
    "muhasebe_muduru": ["invoice_manage", "report_view"],
    "muhasebe":        ["invoice_manage", "report_view"],
}


class RolePermission(Base):
    """Rol bazlı izin tablosu — admin panelinden toggle edilir."""
    __tablename__ = "role_permissions"

    id         = Column(String(36), primary_key=True, default=_uuid)
    role       = Column(String(32), nullable=False, index=True)
    permission = Column(String(64), nullable=False)
    allowed    = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("role", "permission", name="uq_role_permission"),
    )


class DeskReference(Base):
    """micedesk'in references tablosunu okumak için hafif model (read-only bridge)."""
    __tablename__ = "references"
    __table_args__ = {"extend_existing": True}

    id         = Column(String(36), primary_key=True, default=_uuid)
    ref_no     = Column(String(40))
    title      = Column(String(300))
    customer_id = Column(String(36))
    owner_id   = Column(String(36))
    # --- miceapp suite: event artık referans YARATIYOR (desk okur) ---
    company_id = Column(String(36))          # desk'in görmesi için (müşterinin company_id'si)
    event_type = Column(String(50))
    check_in   = Column(Date)
    check_out  = Column(Date)
    status     = Column(String(30), default="aktif")
    created_by = Column(String(36))
    created_at = Column(DateTime, default=_now)


class DeskCreditCard(Base):
    """micedesk credit_cards tablosunu OKUMAK için bridge — HBF kredi kartı seçimi."""
    __tablename__ = "credit_cards"
    __table_args__ = {"extend_existing": True}

    id           = Column(String(36), primary_key=True)
    company_id   = Column(String(36))
    name         = Column(String(100))
    bank_name    = Column(String(100))
    last4        = Column(String(4))
    credit_limit = Column(Float, default=0.0)


class DeskCreditCardTxn(Base):
    """micedesk credit_card_txns — HBF kredi kartı harcaması kartın limitinden düşsün diye YAZILIR."""
    __tablename__ = "credit_card_txns"
    __table_args__ = {"extend_existing": True}

    id                = Column(String(36), primary_key=True, default=_uuid)
    company_id        = Column(String(36))
    card_id           = Column(String(36))
    txn_date          = Column(Date)
    amount            = Column(Float)
    description       = Column(String(300))
    is_refund         = Column(Boolean, default=False)
    expense_report_id = Column(String(36))   # HBF bağı (sync/temizlik için)
