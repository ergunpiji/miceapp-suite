"""
RBAC v2 — Departman bazlı erişim kontrolü.

İki katmanlı erişim:
  1) Modül erişimi (screen-level): departman → modül matrisi
  2) Row-level filtreleme: user'ın departmanlarına göre query filter

GM/admin/super_admin bypass: hepsi görür.

Env: RBAC_V2_ENFORCE=false → tüm filtreler kapalı (acil geri dönüş için).
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy.orm import Query, Session

if TYPE_CHECKING:
    from models import User

ENFORCE = os.environ.get("RBAC_V2_ENFORCE", "true").lower() not in ("false", "0", "no")


# ---------------------------------------------------------------------------
# MODÜL KATALOĞU
# ---------------------------------------------------------------------------

# key → (label, default_departments)
# default_departments: bu modülü hangi departmanlar varsayılan olarak görür
# (sadece seed sırasında kullanılır; runtime'da ModuleAccess tablosu kanonik)
MODULES = {
    "dashboard":            ("Dashboard",              ["*"]),
    "customers":            ("Müşteriler",             ["sales", "accounting"]),
    "references":           ("Referanslar",            ["sales", "operations"]),
    "invoices":             ("Faturalar",              ["sales", "accounting"]),
    "cash":                 ("Kasa",                   ["accounting"]),
    "banks":                ("Banka Hesapları",        ["accounting"]),
    "cheques":              ("Çekler",                 ["accounting"]),
    "credit_cards":         ("Kredi Kartları",         ["accounting"]),
    "vendors":              ("Tedarikçiler",           ["accounting", "operations"]),
    "general_expenses":     ("İşletme Giderleri",      ["accounting"]),
    "fund_pools":           ("Fon Havuzları",          ["accounting"]),
    "budgets":              ("Bütçe",                  ["accounting"]),
    "payments_weekly":      ("Haftalık Ödeme Listesi", ["accounting"]),
    "payment_instructions": ("Ödeme Talimatları",      ["accounting"]),
    "employees":            ("Personel",               ["hr"]),
    "leaves":               ("İzinler",                ["hr"]),
    "advances":             ("Avanslar",               ["hr", "accounting"]),
    "hbf":                  ("Harcama Bildirim",       ["hr", "accounting"]),
    "bordro":               ("Bordro",                 ["hr"]),
    "reports_financial":    ("Finans Raporları",       ["accounting"]),
    "reports_hr":           ("İK Raporları",           ["hr"]),
    "tax_reports":          ("Vergi Raporları",        ["accounting"]),
    "edefter":              ("E-Defter",               ["accounting"]),
    "einvoice":             ("E-Fatura",               ["accounting"]),
    "sales_requests":       ("Fatura Talepleri",       ["sales", "accounting"]),
}


# ---------------------------------------------------------------------------
# Screen-level (modül erişimi)
# ---------------------------------------------------------------------------

# Muhasebe ve İK çalışanları: admin gibi tüm operasyonel alanları görür/kullanır.
# TEK fark: "Yönetim" bölümünü (kullanıcı/rol/departman/modül/şirket profili) GÖREMEZ
# ve giremez — o alan ayrıca is_admin (template) + require_admin (route) ile korunur.
# GM'e özel onay yetkileri (payment_list_approve vb.) check_permission ile ayrı; açılmaz.
# Geriye-dönük referans: bu roller artık kanonik roles.py'de
# CAP_FINANCE_VIEW_ALL yeteneğiyle temsil edilir.
FULL_ACCESS_ROLES = {"muhasebe", "muhasebe_muduru", "ik", "insan_kaynaklari"}


def _bypass(user: "User") -> bool:
    """GM / admin / super_admin + finance.view_all yeteneği her şeyi (Yönetim
    hariç) görür. Yetenekler kanonik roles.py'den gelir."""
    if not ENFORCE:
        return True
    if not user:
        return False
    from roles import has_capability, CAP_FINANCE_VIEW_ALL
    return bool(
        user.is_approver or user.is_admin
        or has_capability(user.role, CAP_FINANCE_VIEW_ALL)
    )


# Kişisel modüller: her user kendi adına erişebilir, içerik row-level filter ile
# kısıtlanır (kendi izni, kendi avansı, kendi HBF'i).
# NOT: "employees" KAPALI — çalışan listesi yalnızca HR/admin/GM görür.
# Kullanıcı kendi profilini /profile altından düzenler.
PERSONAL_MODULES = {
    "dashboard",
    "leaves",      # kendi izin talepleri
    "advances",    # kendi avansları
    "hbf",         # kendi harcama bildirimleri
}


def user_can_see_module(user: "User", module_key: str) -> bool:
    """Bu user bu modülün sayfasını görebilir mi?"""
    if user is None:
        return False
    if _bypass(user):
        return True
    # Kişisel modüller herkese açık — içerik row-level filtreleyle kısıtlanır
    if module_key in PERSONAL_MODULES:
        return True
    depts = user.departments or []
    if not depts:
        return False
    for dept in depts:
        if not dept.active:
            continue
        for ma in (dept.module_access or []):
            if ma.module_key == module_key and ma.can_view:
                return True
    return False


def user_can_edit_module(user: "User", module_key: str) -> bool:
    """Bu user bu modülde yazma yapabilir mi?

    Kişisel modüller için True döner — kendi izin/avans/HBF talebi yaratabilir.
    Başkasının kaydına yazma yetkisi row-level kontrolüyle ayrıca doğrulanır.
    """
    if user is None:
        return False
    if _bypass(user):
        return True
    if module_key in PERSONAL_MODULES:
        return True
    depts = user.departments or []
    for dept in depts:
        if not dept.active:
            continue
        for ma in (dept.module_access or []):
            if ma.module_key == module_key and ma.can_edit:
                return True
    return False


# ---------------------------------------------------------------------------
# Row-level (data filtering)
#
# Pattern: visible_X_query(db, user) → Query
# Caller: visible_invoices_query(db, user).filter(...).all()
# ---------------------------------------------------------------------------

def _company_scope(query: Query, model_cls, user: "User") -> Query:
    """company_id filtresini uygula — multi-tenant temel izolasyon.
    Super_admin tüm şirketleri görebilir, diğerleri sadece kendi şirketini."""
    if user.is_super_admin:
        # Platform sahibi: aktif şirket seçiliyse ona scope, yoksa tüm şirketler
        _ac = getattr(user, "_active_company_id", None)
        if _ac and hasattr(model_cls, "company_id"):
            return query.filter(model_cls.company_id == _ac)
        return query
    if hasattr(model_cls, "company_id"):
        return query.filter(model_cls.company_id == user.company_id)
    return query


def _sales_visible_owner_ids(db: Session, user: "User") -> list[int]:
    """Sales user'ın görmeye yetkili olduğu owner_id listesi.
    - mudur rolünde: kendi takımı (manager_id chain) + kendisi
    - kullanici: yalnızca kendisi
    """
    from models import User as _User
    if user.role == "mudur":
        team = db.query(_User.id).filter(_User.manager_id == user.id).all()
        return [t[0] for t in team] + [user.id]
    return [user.id]


def _teammate_ids(db: Session, user: "User") -> list:
    """Kullanıcıyla aynı departmandaki aktif user ID listesi (takım izolasyonu için).
    Kullanıcının bağlı olduğu tüm departmanları paylaşan diğer aktif kullanıcıları döndürür.
    Departmansız kullanıcı için yalnızca kendi ID'si döner."""
    from models import User as _User, UserDepartment
    dept_ids = [d.id for d in (user.departments or []) if d.active]
    if not dept_ids:
        return [user.id]
    rows = (
        db.query(_User.id)
        .join(UserDepartment, _User.id == UserDepartment.user_id)
        .filter(
            UserDepartment.department_id.in_(dept_ids),
            _User.company_id == user.company_id,
            _User.active == True,  # noqa: E712
        )
        .distinct()
        .all()
    )
    ids = [r[0] for r in rows]
    if user.id not in ids:
        ids.append(user.id)
    return ids


def visible_customers_query(db: Session, user: "User") -> Query:
    from models import Customer
    base = _company_scope(db.query(Customer), Customer, user)
    if _bypass(user):
        return base
    if user.has_department_key("accounting") or user.has_department_key("operations"):
        return base
    # Satış takımı: yalnızca kendi takım üyelerine ait müşteriler (takım izolasyonu)
    teammate_ids = _teammate_ids(db, user)
    if teammate_ids:
        return base.filter(Customer.owner_id.in_(teammate_ids))
    return base.filter(False)


def visible_references_query(db: Session, user: "User") -> Query:
    from models import Reference
    base = _company_scope(db.query(Reference), Reference, user)
    if _bypass(user):
        return base
    if user.has_department_key("accounting") or user.has_department_key("operations"):
        return base
    # Satış takımı: yalnızca kendi takım üyelerinin açtığı referanslar (owner_id)
    teammate_ids = _teammate_ids(db, user)
    if teammate_ids:
        return base.filter(Reference.owner_id.in_(teammate_ids))
    return base.filter(False)


def visible_invoices_query(db: Session, user: "User") -> Query:
    """Fatura görünürlüğü: muhasebe hepsini, sales kendi takım müşterilerinin faturalarını."""
    from models import Invoice, Customer
    base = _company_scope(db.query(Invoice), Invoice, user)
    if _bypass(user):
        return base
    if user.has_department_key("accounting") or user.has_department_key("operations"):
        return base
    # Satış takımı: onay kuyruğundaki (current_approver_id) ve takım müşterilerine ait faturalar
    teammate_ids = _teammate_ids(db, user)
    if teammate_ids:
        return base.outerjoin(Customer, Invoice.customer_id == Customer.id).filter(
            Customer.owner_id.in_(teammate_ids)
        )
    return base.filter(False)


def visible_cheques_query(db: Session, user: "User") -> Query:
    from models import Cheque
    base = _company_scope(db.query(Cheque), Cheque, user)
    if _bypass(user) or user.has_department_key("accounting"):
        return base
    return base.filter(False)


def visible_employees_query(db: Session, user: "User") -> Query:
    """Personel listesi: HR depo + GM/admin; kullanıcı kendi kaydını her zaman görür."""
    from models import Employee
    base = _company_scope(db.query(Employee), Employee, user)
    if _bypass(user) or user.has_department_key("hr"):
        return base
    # Kendi employee kaydı varsa onu göster
    return base.filter(Employee.user_id == user.id)


def visible_advances_query(db: Session, user: "User") -> Query:
    """Avanslar: HR/muhasebe + GM hepsini; kullanıcı kendi avanslarını; müdür takımının."""
    from models import EmployeeAdvance, Employee
    base = _company_scope(db.query(EmployeeAdvance), EmployeeAdvance, user)
    if _bypass(user) or user.has_department_key("hr") or user.has_department_key("accounting"):
        return base
    # mudur kendi takımı görür
    if user.role == "mudur":
        team_user_ids = [u.id for u in _team_user_ids(db, user)]
        return base.join(Employee, EmployeeAdvance.employee_id == Employee.id).filter(
            Employee.user_id.in_(team_user_ids + [user.id])
        )
    return base.join(Employee, EmployeeAdvance.employee_id == Employee.id).filter(
        Employee.user_id == user.id
    )


def visible_hbf_query(db: Session, user: "User") -> Query:
    """HBF: HR/muhasebe + GM hepsini; kullanıcı kendi formları; müdür takımının."""
    from models import HBF
    base = _company_scope(db.query(HBF), HBF, user)
    if _bypass(user) or user.has_department_key("hr") or user.has_department_key("accounting"):
        return base
    if user.role == "mudur":
        team_ids = [u.id for u in _team_user_ids(db, user)] + [user.id]
        return base.filter(HBF.created_by.in_(team_ids))
    return base.filter(HBF.created_by == user.id)


def visible_leaves_query(db: Session, user: "User") -> Query:
    """İzinler: HR/GM hepsini; kullanıcı kendi izinleri; müdür takımının."""
    from models import LeaveRequest
    base = _company_scope(db.query(LeaveRequest), LeaveRequest, user)
    if _bypass(user) or user.has_department_key("hr"):
        return base
    if user.role == "mudur":
        team_ids = [u.id for u in _team_user_ids(db, user)] + [user.id]
        return base.filter(LeaveRequest.requested_by.in_(team_ids))
    return base.filter(LeaveRequest.requested_by == user.id)


def _team_user_ids(db: Session, manager: "User") -> list:
    """Müdüre raporlayan user'ları getir (User.manager_id chain, 1 seviye)."""
    from models import User
    return db.query(User).filter(User.manager_id == manager.id).all()


# ---------------------------------------------------------------------------
# Helper: ID bazlı erişim check (detail page için)
# ---------------------------------------------------------------------------

def visible_sales_requests_query(db: Session, user: "User") -> Query:
    """Fatura talepleri: muhasebe hepsini, satış ekibi kendi takımının taleplerini görür."""
    from models import SalesInvoiceRequest
    base = _company_scope(db.query(SalesInvoiceRequest), SalesInvoiceRequest, user)
    if _bypass(user):
        return base
    if user.has_department_key("accounting"):
        return base
    # Satış takımı: yalnızca kendi takım üyelerinin talepleri
    teammate_ids = _teammate_ids(db, user)
    if teammate_ids:
        return base.filter(SalesInvoiceRequest.requested_by.in_(teammate_ids))
    return base.filter(False)


def can_access_customer(db: Session, user: "User", customer_id: int) -> bool:
    return visible_customers_query(db, user).filter_by(id=customer_id).first() is not None


def can_access_reference(db: Session, user: "User", reference_id: int) -> bool:
    return visible_references_query(db, user).filter_by(id=reference_id).first() is not None


def can_access_invoice(db: Session, user: "User", invoice_id: int) -> bool:
    return visible_invoices_query(db, user).filter_by(id=invoice_id).first() is not None
