"""
micedesk — Ana FastAPI uygulama girişi
Çalıştır: uvicorn app:app --reload
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# prizma-einvoice paketini sys.path'e ekle (editable install yerine)
_pkg_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "packages", "prizma-einvoice", "src",
)
if os.path.isdir(_pkg_path) and _pkg_path not in sys.path:
    sys.path.insert(0, _pkg_path)

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import init_db, engine, get_db
from models import Base
from auth import get_current_user, require_admin
from templates_config import templates

# E-Fatura modülünü init et — register_models Base'e tablolar ekler.
# init_db()'den ÖNCE yapılmalı ki create_all yeni tabloları da yaratsın.
try:
    from prizma_einvoice import EInvoiceModule
    einvoice_module = EInvoiceModule(
        host_base=Base,
        engine=engine,
        config={"provider": "fake"},
        get_db_dependency=get_db,
        require_admin_dependency=require_admin,
        get_current_user_dependency=get_current_user,
    )
    print("[einvoice] modül init edildi (provider: fake)", flush=True)
except Exception as exc:  # noqa: BLE001
    einvoice_module = None
    print(f"[einvoice] modül init edilemedi: {exc}", flush=True)

# ---------------------------------------------------------------------------
# Veritabanı başlat
# ---------------------------------------------------------------------------

_db_url = os.environ.get("DATABASE_URL", "")
if _db_url.startswith("postgres"):
    print("[DB] PostgreSQL bağlantısı kullanılıyor", flush=True)
elif not _db_url or _db_url.startswith("sqlite"):
    print("[DB] SQLite kullanılıyor", flush=True)

if os.environ.get("SKIP_INIT_DB") == "1":
    print("[DB] SKIP_INIT_DB=1 — init/migration atlandı (şema zaten kurulu)", flush=True)
else:
    init_db()

# ---------------------------------------------------------------------------
# FastAPI uygulaması
# ---------------------------------------------------------------------------

app = FastAPI(
    title="micedesk",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Nav-badge middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def nav_counts_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or "." in path.split("/")[-1]:
        request.state.nav_counts = {}
        request.state.enabled_modules = set()
        request.state.company_id = None
        request.state.current_company = None
        request.state.current_user = None
        return await call_next(request)

    counts = {}
    enabled_modules = set()
    from auth import decode_token, COOKIE_NAME
    from database import SessionLocal
    from sqlalchemy import func
    from models import Invoice, PaymentInstruction, SystemSetting

    token = request.cookies.get(COOKIE_NAME)
    if token:
        payload = decode_token(token)
        if payload:
            db = SessionLocal()
            try:
                from models import (
                    Invoice, PaymentInstruction, SystemSetting,
                    LeaveRequest, EmployeeAdvance, HBF,
                    User as UserModel, Employee, Company, Reference,
                    ExpenseReport,
                )
                user_id_raw = payload.get("sub")

                # Kullanıcının kendisini ve şirketini çek (RBAC v2: can_see/can_edit için gerekli)
                current_user = None
                company_id = None
                current_company = None
                if user_id_raw:
                    current_user = db.query(UserModel).filter(UserModel.id == user_id_raw).first()
                    if current_user:
                        company_id = str(current_user.company_id) if current_user.company_id else None
                        # Departments + module_access'i ZORLA pre-load et — session
                        # kapanınca lazy-load detached-instance hatası vermesin.
                        for _dept in (current_user.departments or []):
                            _ = _dept.module_access  # force eager load
                        # Session'dan ayır — request boyunca obj kullanılacak
                        db.expunge(current_user)
                if company_id:
                    current_company = db.query(Company).filter(Company.id == company_id).first()
                    if current_company:
                        db.expunge(current_company)
                request.state.current_user = current_user
                request.state.company_id = company_id
                request.state.current_company = current_company

                if payload.get("is_admin") and company_id:
                    counts["invoices_unpaid"] = (
                        db.query(func.count(Invoice.id))
                        .filter(Invoice.company_id == company_id,
                                Invoice.status.in_(["approved", "partial"]),
                                Invoice.deleted_at == None)  # noqa: E711
                        .scalar() or 0
                    )
                if company_id:
                    counts["pending_instructions"] = (
                        db.query(func.count(PaymentInstruction.id))
                        .filter(PaymentInstruction.company_id == company_id,
                                PaymentInstruction.status == "pending")
                        .scalar() or 0
                    )

                # Bekleyen izin / avans / HBF sayıları (müdür+ için)
                if user_id_raw and company_id:
                    _ROLE_ORDER = ["kullanici", "mudur", "genel_mudur", "admin", "super_admin"]
                    user_role = (
                        db.query(UserModel.role)
                        .filter(UserModel.id == user_id_raw)
                        .scalar() or "kullanici"
                    )
                    role_idx = _ROLE_ORDER.index(user_role) if user_role in _ROLE_ORDER else 0

                    p_leaves = p_adv = p_hbf = 0
                    if role_idx >= _ROLE_ORDER.index("mudur"):
                        if role_idx >= _ROLE_ORDER.index("genel_mudur"):
                            p_leaves = (
                                db.query(func.count(LeaveRequest.id))
                                .filter(LeaveRequest.company_id == company_id,
                                        LeaveRequest.status.in_(["talep", "mudur_onayladi"]))
                                .scalar() or 0
                            )
                            p_adv = (
                                db.query(func.count(EmployeeAdvance.id))
                                .filter(EmployeeAdvance.company_id == company_id,
                                        EmployeeAdvance.approval_status == "talep")
                                .scalar() or 0
                            )
                            # Birleşik HBF: onay bekleyen (submitted) — desk formu da buraya yazar
                            p_hbf = (
                                db.query(func.count(ExpenseReport.id))
                                .filter(ExpenseReport.company_id == company_id,
                                        ExpenseReport.status == "submitted")
                                .scalar() or 0
                            )
                        else:
                            # Sadece müdür: kendi ekibinin bekleyenleri
                            team_ids = [
                                e[0] for e in
                                db.query(Employee.id)
                                .join(UserModel, Employee.user_id == UserModel.id)
                                .filter(UserModel.manager_id == user_id_raw,
                                        UserModel.active == True)  # noqa: E712
                                .all()
                            ]
                            if team_ids:
                                p_leaves = (
                                    db.query(func.count(LeaveRequest.id))
                                    .filter(LeaveRequest.employee_id.in_(team_ids),
                                            LeaveRequest.status == "talep")
                                    .scalar() or 0
                                )
                                p_adv = (
                                    db.query(func.count(EmployeeAdvance.id))
                                    .filter(EmployeeAdvance.employee_id.in_(team_ids),
                                            EmployeeAdvance.approval_status == "talep")
                                    .scalar() or 0
                                )
                            # Birleşik HBF: müdür de şirketin onay bekleyen formlarını görür
                            p_hbf = (
                                db.query(func.count(ExpenseReport.id))
                                .filter(ExpenseReport.company_id == company_id,
                                        ExpenseReport.status == "submitted")
                                .scalar() or 0
                            )
                    counts["pending_leaves"]   = p_leaves
                    counts["pending_advances"] = p_adv
                    counts["pending_hbf"]      = p_hbf

                    # Ortak HBF — muhasebe ödeme/kapatma bekleyen (onaylandi)
                    if user_role in ("muhasebe", "muhasebe_muduru", "admin", "super_admin"):
                        counts["pending_hbf_muhasebe"] = (
                            db.query(func.count(ExpenseReport.id))
                            .filter(ExpenseReport.company_id == company_id,
                                    ExpenseReport.status == "onaylandi")
                            .scalar() or 0
                        )
                        # Ön ödeme — GM onaylı, muhasebe ödemesi bekleyen
                        from models import EventPrepaymentRequest as _EPR
                        counts["pending_prepayment"] = (
                            db.query(func.count(_EPR.id))
                            .filter(_EPR.company_id == company_id,
                                    _EPR.status == "approved")
                            .scalar() or 0
                        )

                    # GM+ için bekleyen referans kapanış/reaktivasyon onayları
                    p_refs = 0
                    if role_idx >= _ROLE_ORDER.index("genel_mudur"):
                        p_refs = (
                            db.query(func.count(Reference.id))
                            .filter(Reference.company_id == company_id,
                                    Reference.approval_status.in_([
                                        "kapanış_talep", "mudur_onayladi", "reaktivasyon_talep"
                                    ]))
                            .scalar() or 0
                        )
                    counts["pending_refs"]     = p_refs
                    counts["pending_total"]    = p_leaves + p_adv + p_hbf + p_refs

                # Onayını bekleyen faturalar (current_approver_id = bu user)
                if user_id_raw and company_id:
                    counts["my_pending_invoices"] = (
                        db.query(func.count(Invoice.id))
                        .filter(Invoice.company_id == company_id,
                                Invoice.current_approver_id == user_id_raw,
                                Invoice.approval_status == "onay_bekliyor",
                                Invoice.deleted_at == None)  # noqa: E711
                        .scalar() or 0
                    )
                    # Tüm onay-bekleyen faturalar (muhasebe sidebar sayacı)
                    counts["all_pending_invoices"] = (
                        db.query(func.count(Invoice.id))
                        .filter(Invoice.company_id == company_id,
                                Invoice.approval_status == "onay_bekliyor",
                                Invoice.deleted_at == None)  # noqa: E711
                        .scalar() or 0
                    )

                # Havuzdaki referanssız faturalar (tüm satış kullanıcılarına görünür)
                if company_id:
                    from models import SalesInvoiceRequest as _SIR
                    counts["pool_invoices"] = (
                        db.query(func.count(Invoice.id))
                        .filter(Invoice.company_id == company_id,
                                Invoice.in_pool == True,  # noqa: E712
                                Invoice.deleted_at == None)  # noqa: E711
                        .scalar() or 0
                    )
                    # Bekleyen fatura talepleri (muhasebe + talep sahibi)
                    counts["pending_invoice_requests"] = (
                        db.query(func.count(_SIR.id))
                        .filter(_SIR.company_id == company_id,
                                _SIR.status == "beklemede")
                        .scalar() or 0
                    )

                # Aktif modülleri oku (Yönetim → Modüller'den ayarlanır)
                module_settings = db.query(SystemSetting).filter(
                    SystemSetting.key.like("module_%_enabled")
                ).all()
                for s in module_settings:
                    if s.value == "1":
                        # 'module_einvoice_enabled' → 'einvoice'
                        key = s.key[len("module_"):-len("_enabled")]
                        enabled_modules.add(key)
            except Exception:
                pass
            finally:
                db.close()

    request.state.nav_counts = counts
    request.state.enabled_modules = enabled_modules
    if not hasattr(request.state, "current_company"):
        request.state.current_company = None
    if not hasattr(request.state, "company_id"):
        request.state.company_id = None
    if not hasattr(request.state, "current_user"):
        request.state.current_user = None
    return await call_next(request)


# ---------------------------------------------------------------------------
# Hata yöneticileri
# ---------------------------------------------------------------------------

def _error_current_user(request: Request):
    """Hata sayfalarında sidebar düzgün render olsun diye cookie'den kullanıcıyı çöz
    (departman+modül erişimi eager yüklenir; lazy-load için açık session gerekmez)."""
    try:
        from auth import decode_token, COOKIE_NAME
        from database import SessionLocal
        from models import User as _U, Department
        from sqlalchemy.orm import joinedload
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        payload = decode_token(token)
        if not payload:
            return None
        db = SessionLocal()
        try:
            return (
                db.query(_U)
                .options(joinedload(_U.departments).joinedload(Department.module_access))
                .filter(_U.id == payload.get("sub"))
                .first()
            )
        finally:
            db.close()
    except Exception:
        return None


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    _cu = _error_current_user(request)
    if exc.status_code == 403:
        return templates.TemplateResponse(
            "errors/403.html",
            {"request": request, "current_user": _cu, "detail": exc.detail},
            status_code=403,
        )
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "errors/404.html",
            {"request": request, "current_user": _cu},
            status_code=404,
        )
    return templates.TemplateResponse(
        "errors/generic.html",
        {"request": request, "current_user": _cu,
         "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


# ---------------------------------------------------------------------------
# Kök yönlendirme
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Router'ları dahil et
# ---------------------------------------------------------------------------

from routers import auth as auth_router
from routers import dashboard as dashboard_router
from routers import references as references_router
from routers import customers as customers_router
from routers import users as users_router
from routers import invoices as invoices_router
from routers import vendors as vendors_router
from routers import cheques as cheques_router
from routers import cash as cash_router
from routers import bank_accounts as bank_accounts_router
from routers import credit_cards as credit_cards_router
from routers import general_expenses as general_expenses_router
from routers import employees as employees_router
from routers import reports as reports_router
from routers import hbf as hbf_router
from routers import hbf_muhasebe as hbf_muhasebe_router
from routers import expenses as expenses_router
from routers import prepayment_odeme as prepayment_odeme_router
from routers import advances as advances_router
from routers import fund_pools as fund_pools_router
from routers import payments as payments_router
from routers import payment_instructions as payment_instructions_router
from routers import profile as profile_router
from routers import admin_modules as admin_modules_router
from routers import einvoice_host as einvoice_host_router
from routers import tax_reports as tax_reports_router
from routers import edefter as edefter_router
from routers import company_profile as company_profile_router
from routers import admin_roles as admin_roles_router
from routers import leaves as leaves_router
from routers import admin_leaves as admin_leaves_router
from routers import bordro as bordro_router
from routers import admin_companies as admin_companies_router
from routers import admin_vendor_types as admin_vendor_types_router
from routers import notifications as notifications_router
from routers import admin_backup as admin_backup_router
from routers import admin_demo as admin_demo_router
from routers import help as help_router
from routers import admin_departments as admin_departments_router
from routers import admin_approval_limits as admin_approval_limits_router
from routers import sales_requests as sales_requests_router

app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(references_router.router)
app.include_router(customers_router.router)
app.include_router(users_router.router)
app.include_router(invoices_router.router)
app.include_router(vendors_router.router)
app.include_router(cheques_router.router)
app.include_router(cash_router.router)
app.include_router(bank_accounts_router.router)
app.include_router(credit_cards_router.router)
app.include_router(general_expenses_router.router)
app.include_router(employees_router.router)
app.include_router(reports_router.router)
app.include_router(hbf_router.router)
app.include_router(hbf_muhasebe_router.router)
app.include_router(expenses_router.router)
app.include_router(prepayment_odeme_router.router)
app.include_router(advances_router.router)
app.include_router(fund_pools_router.router)
app.include_router(payments_router.router)
app.include_router(payment_instructions_router.router)
app.include_router(profile_router.router)
app.include_router(admin_modules_router.router)
app.include_router(einvoice_host_router.router)
app.include_router(tax_reports_router.router)
app.include_router(edefter_router.router)
app.include_router(company_profile_router.router)
app.include_router(admin_roles_router.router)
app.include_router(leaves_router.router)
app.include_router(admin_leaves_router.router)
app.include_router(bordro_router.router)
app.include_router(admin_companies_router.router)
app.include_router(admin_vendor_types_router.router)
app.include_router(notifications_router.router)
app.include_router(admin_backup_router.router)
app.include_router(admin_demo_router.router)
app.include_router(help_router.router)
app.include_router(admin_departments_router.router)
app.include_router(admin_approval_limits_router.router)
app.include_router(sales_requests_router.router)

# E-Fatura modülünü mount et (router /einvoice/* prefix'ile eklenir).
# Endpoint'ler her zaman erişilebilir; aktif/pasif kontrolü feature flag ile
# (admin_modules sayfasından) yönetilir.
if einvoice_module is not None:
    try:
        einvoice_module.install(app)
        print("[einvoice] router /einvoice/* mount edildi", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[einvoice] router mount edilemedi: {exc}", flush=True)


# ---------------------------------------------------------------------------
# Dosya sunumu — R2 veya yerel fallback
# ---------------------------------------------------------------------------

from fastapi.responses import FileResponse as _FileResponse

@app.get("/files/{key:path}", name="serve_file")
async def serve_file(
    key: str,
    current_user=Depends(get_current_user),
):
    """Yüklenen dosyaları güvenli sunar. R2 varsa presigned URL'e redirect eder.
    key 'static/' ile başlayabilir (eski kayıtlar) veya başlamayabilir (yeni kayıtlar)."""
    from fastapi import HTTPException
    from storage_helper import R2_ENABLED, get_file_url
    # Normalize: eski kayıtlarda 'static/' prefix'i var
    r2_key = key[len("static/"):] if key.startswith("static/") else key
    if R2_ENABLED:
        url = get_file_url(r2_key)
        return RedirectResponse(url=url, status_code=302)
    # Yerel: static/ dizini içinde kalması zorunlu (path traversal koruması)
    static_base = os.path.abspath("static")
    candidate = os.path.normpath(os.path.join(static_base, r2_key))
    if not candidate.startswith(static_base + os.sep) and candidate != static_base:
        raise HTTPException(status_code=403, detail="Erişim reddedildi")
    if not os.path.isfile(candidate):
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return _FileResponse(candidate)
