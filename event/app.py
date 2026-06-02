"""
Satın Alma — Ana FastAPI uygulama girişi
Çalıştır: uvicorn app:app --reload
"""

from __future__ import annotations

import os

# .env dosyası varsa yükle (python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import Base, engine, seed_data, migrate_db, _seed_event_company
from templates_config import templates

# ---------------------------------------------------------------------------
# Veritabanı başlat
# ---------------------------------------------------------------------------

_db_url = os.environ.get("DATABASE_URL", "")
if _db_url.startswith("postgres"):
    print(f"[DB] PostgreSQL bağlantısı kullanılıyor ✓", flush=True)
elif _db_url.startswith("sqlite") or not _db_url:
    print(f"[DB] ⚠️  SQLite kullanılıyor — veriler her restart'ta SİLİNİR!", flush=True)
else:
    print(f"[DB] Bağlantı tipi: {_db_url[:20]}...", flush=True)

if os.environ.get("RESET_DB") == "1":
    print("[db] RESET_DB=1 — schema sıfırlanıyor (CASCADE)...", flush=True)
    from sqlalchemy import text
    with engine.connect() as _conn:
        _conn.execute(text("DROP SCHEMA public CASCADE"))
        _conn.execute(text("CREATE SCHEMA public"))
        _conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        _conn.commit()
    print("[db] Schema sıfırlandı.", flush=True)

import os as _os
if _os.environ.get("SKIP_INIT_DB") == "1":
    print("[db] SKIP_INIT_DB=1 — init/migration atlandı (şema zaten kurulu)", flush=True)
else:
    Base.metadata.create_all(bind=engine)
    migrate_db()
    seed_data()
    _seed_event_company()

# ---------------------------------------------------------------------------
# FastAPI uygulaması
# ---------------------------------------------------------------------------
app = FastAPI(
    title="miceapp",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ---------------------------------------------------------------------------
# Statik dosyalar
# ---------------------------------------------------------------------------
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js",  exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# Hata yöneticileri
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Nav-badge middleware — her sayfada bekleyen işlem sayaçları
# ---------------------------------------------------------------------------

@app.middleware("http")
async def nav_counts_middleware(request: Request, call_next):
    """Cookie'den kullanıcıyı okur, role göre nav badge sayılarını hesaplar."""
    from auth import decode_token, COOKIE_NAME
    from database import SessionLocal
    from sqlalchemy import text as _text

    # Statik dosyalar veya API dokümantasyonu için veritabanına gitme
    path = request.url.path
    if path.startswith("/static") or path.startswith("/api") or "." in path.split("/")[-1]:
        return await call_next(request)

    counts = {}
    token = request.cookies.get(COOKIE_NAME)
    if token:
        payload = decode_token(token)
        if payload:
            uid  = payload.get("sub", "")
            role = payload.get("role", "")
            db = SessionLocal()
            try:
                from models import User as _User
                _user_obj = db.query(_User).filter(_User.id == uid).first()
                _is_gm = _user_obj.is_gm if _user_obj else False

                if role in ("mudur", "admin", "muhasebe_muduru") or _is_gm:
                    # GM onayı bekleyen fatura talepleri
                    counts["inv_pending_gm"] = db.execute(
                        _text("SELECT COUNT(*) FROM invoices WHERE status='pending'")
                    ).scalar() or 0
                    # Benim onayımı bekleyen faturalar (current_approver_id = bu kullanıcı)
                    counts["inv_my_pending"] = db.execute(
                        _text("SELECT COUNT(*) FROM invoices WHERE status='pending' AND current_approver_id=:uid"),
                        {"uid": uid}
                    ).scalar() or 0
                if role in ("muhasebe", "muhasebe_muduru", "admin") or _is_gm:
                    # Muhasebe kesmesi bekleyen faturalar
                    counts["inv_pending_cut"] = db.execute(
                        _text("SELECT COUNT(*) FROM invoices WHERE status='gm_approved'")
                    ).scalar() or 0
                if role in ("mudur", "admin") or _is_gm:
                    # Kapama onayı — GM adımı bekleyen
                    counts["closure_pending_gm"] = db.execute(
                        _text("SELECT COUNT(*) FROM closure_requests WHERE status='pending_gm'")
                    ).scalar() or 0
                if role in ("muhasebe_muduru", "admin") or _is_gm:
                    # Kapama onayı — Muhasebe müdürü adımı
                    counts["closure_pending_finance"] = db.execute(
                        _text("SELECT COUNT(*) FROM closure_requests WHERE status='pending_finance'")
                    ).scalar() or 0
                if role in ("mudur", "admin") or _is_gm:
                    # Kapama onayı — Müdür adımı
                    counts["closure_pending_manager"] = db.execute(
                        _text("SELECT COUNT(*) FROM closure_requests WHERE status='pending_manager'")
                    ).scalar() or 0
                if role == "satinalma":
                    # Satın Alma: atanmamış/bekleyen talepler
                    counts["requests_pending"] = db.execute(
                        _text("SELECT COUNT(*) FROM requests WHERE status='pending'")
                    ).scalar() or 0
                if role in ("yonetici", "asistan"):
                    # PM: kendi bütçeleri fiyatlandırma bekliyor
                    counts["budgets_pending"] = db.execute(
                        _text(
                            "SELECT COUNT(*) FROM budgets b "
                            "JOIN requests r ON r.id=b.request_id "
                            "WHERE b.budget_status='pending_manager' AND r.created_by=:uid"
                        ), {"uid": uid}
                    ).scalar() or 0
                if role in ("mudur", "admin", "muhasebe_muduru") or _is_gm:
                    # Yönetici: tüm bütçeler fiyatlandırma bekliyor (PM'ler için)
                    counts["budgets_pending_all"] = db.execute(
                        _text(
                            "SELECT COUNT(*) FROM budgets "
                            "WHERE budget_status='pending_manager'"
                        )
                    ).scalar() or 0
                if role in ("mudur", "admin") or _is_gm:
                    # Müdür onayı bekleyen faturalar (limit aşıldı, GM onayı gerekiyor)
                    counts["inv_pending_mudur"] = db.execute(
                        _text("SELECT COUNT(*) FROM invoices WHERE status='mudur_approved'")
                    ).scalar() or 0
                # Referans bekleyen faturalar — tüm roller için
                counts["inv_unlinked"] = db.execute(
                    _text("SELECT COUNT(*) FROM invoices WHERE request_id IS NULL AND status != 'cancelled'")
                ).scalar() or 0
                # Kapama talebi bekleyenler — etkinliği tamamlanmış ama henüz closure açılmamış
                if role in ("mudur", "admin", "muhasebe_muduru", "yonetici") or _is_gm:
                    counts["completed_awaiting_closure"] = db.execute(
                        _text(
                            "SELECT COUNT(*) FROM requests r "
                            "WHERE r.status='completed' "
                            "AND NOT EXISTS (SELECT 1 FROM closure_requests c WHERE c.request_id=r.id)"
                        )
                    ).scalar() or 0
                # Ön ödeme talepleri — GM için bekleyen
                if _is_gm:
                    counts["prepayment_pending_gm"] = db.execute(
                        _text("SELECT COUNT(*) FROM prepayment_requests WHERE status='pending_gm'")
                    ).scalar() or 0
                # Ön ödeme talepleri — muhasebe için onaylanmış (ödeme bekliyor)
                if role in ("muhasebe", "muhasebe_muduru", "admin"):
                    counts["prepayment_approved"] = db.execute(
                        _text("SELECT COUNT(*) FROM prepayment_requests WHERE status='approved'")
                    ).scalar() or 0
                # Koordinatör fatura onayları — beklemede
                if _is_gm:
                    try:
                        counts["coordinator_pending"] = db.execute(
                            _text("SELECT COUNT(*) FROM invoices WHERE coordinator_status='beklemede'")
                        ).scalar() or 0
                    except Exception:
                        counts["coordinator_pending"] = 0
                # HBF — bu kullanıcının onayını bekleyen harcama formları
                if _user_obj:
                    try:
                        from routers.expenses import hbf_pending_count_for
                        counts["pending_hbf"] = hbf_pending_count_for(db, _user_obj)
                    except Exception:
                        counts["pending_hbf"] = 0
            except Exception:
                pass
            finally:
                db.close()

    request.state.nav_counts = counts
    response = await call_next(request)
    return response


def _get_error_user(request: Request):
    """Hata sayfaları için cookie'den kullanıcıyı güvenli şekilde çek."""
    try:
        from auth import decode_token, COOKIE_NAME
        from database import SessionLocal
        from models import User as _User
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        payload = decode_token(token)
        if not payload:
            return None
        uid = payload.get("sub")
        if not uid:
            return None
        db = SessionLocal()
        try:
            return db.query(_User).filter(_User.id == uid).first()
        finally:
            db.close()
    except Exception:
        return None


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    _user = _get_error_user(request)
    if exc.status_code == 403:
        return templates.TemplateResponse(
            "errors/403.html",
            {"request": request, "current_user": _user, "detail": exc.detail},
            status_code=403,
        )
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "errors/404.html",
            {"request": request, "current_user": _user},
            status_code=404,
        )
    return templates.TemplateResponse(
        "errors/generic.html",
        {"request": request, "current_user": _user, "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    _user = _get_error_user(request)
    errors = "; ".join(
        f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}"
        for e in exc.errors()
    )
    return templates.TemplateResponse(
        "errors/generic.html",
        {"request": request, "current_user": _user, "status_code": 422,
         "detail": f"Form verisi hatalı: {errors}"},
        status_code=422,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback, logging
    logging.getLogger("miceapp").error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
    _user = _get_error_user(request)
    try:
        return templates.TemplateResponse(
            "errors/generic.html",
            {"request": request, "current_user": _user, "status_code": 500,
             "detail": "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin."},
            status_code=500,
        )
    except Exception:
        return JSONResponse({"detail": "Sunucu hatası"}, status_code=500)


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
from routers import users as users_router
from routers import venues as venues_router
from routers import customers as customers_router
from routers import services as services_router
from routers import requests as requests_router
from routers import budgets as budgets_router
from routers import event_types as event_types_router
from routers import settings as settings_router
from routers import reports as reports_router
from routers import invoices as invoices_router
from routers import email_templates as email_templates_router
from routers import bulk_import as bulk_import_router
from routers import expenses as expenses_router
from routers import notifications as notifications_router
from routers import exchange_rates as exchange_rates_router
from routers import closure as closure_router
from routers import teams as teams_router
from routers import vendors as vendors_router
from routers import library as library_router
from routers import modules as modules_router
from routers import permissions as permissions_router
from routers import prepayment_requests as prepayment_requests_router
from routers import coordinator as coordinator_router
from routers import my_requests as my_requests_router

app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(users_router.router)
app.include_router(venues_router.router)
app.include_router(customers_router.router)
app.include_router(services_router.router)
app.include_router(requests_router.router)
app.include_router(budgets_router.router)
app.include_router(event_types_router.router)
app.include_router(settings_router.router)
app.include_router(reports_router.router)
app.include_router(invoices_router.router)
app.include_router(email_templates_router.router)
app.include_router(bulk_import_router.router)
app.include_router(expenses_router.router)
app.include_router(expenses_router.undoc_router)
app.include_router(notifications_router.router)
app.include_router(exchange_rates_router.router)
app.include_router(closure_router.router)
app.include_router(teams_router.router)
app.include_router(vendors_router.router)
app.include_router(library_router.router)
app.include_router(modules_router.router)
app.include_router(permissions_router.router)
app.include_router(prepayment_requests_router.router)
app.include_router(coordinator_router.router)
app.include_router(my_requests_router.router)

from routers import gsk as gsk_router
app.include_router(gsk_router.router)

# ---------------------------------------------------------------------------
# Operasyon Ajanı — sub-app olarak mount et (/operasyon/...)
# ---------------------------------------------------------------------------
import sys as _sys
import importlib as _il

_oa_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents", "operasyon")
os.environ.setdefault("OA_URL_PREFIX", "/operasyon")


def _mount_operasyon():
    """
    Operasyon agent'ı Satın Alma modülleriyle çakışmadan yükle.

    Satın Alma ve operasyon her ikisi de 'database', 'models', 'config',
    'templates_config', 'routers' gibi aynı isimli modüller kullanıyor.
    sys.modules önbelleğinde Satın Alma'inkiler zaten yüklü olduğundan,
    operasyon yüklenirken geçici olarak saklanıp sonra geri yükleniyor.
    """
    _bare = {"database", "models", "config", "templates_config", "main"}

    # Satın Alma'in çakışan modüllerini geçici olarak sakla
    _stash: dict = {}
    for _n in list(_sys.modules.keys()):
        if _n in _bare or _n == "routers" or _n.startswith("routers.") or _n.startswith("services."):
            _stash[_n] = _sys.modules.pop(_n)

    _sys.path.insert(0, _oa_dir)
    try:
        _oa_mod = _il.import_module("main")   # agents/operasyon/main.py
        _app = _oa_mod.app

        # Tablolar henüz yoksa yarat — burada çağırmak kritik:
        # operasyon modülleri hâlâ düz isimlerle sys.modules'ta
        # (database, models) olduğundan init_db() doğru Base'i bulur.
        _oa_db = _il.import_module("database")
        _oa_db.init_db()
    finally:
        # Operasyon'un yüklediği modülleri _oa.* ismi altında sakla
        for _n in list(_sys.modules.keys()):
            if (_n in _bare or _n == "routers" or
                    _n.startswith("routers.") or _n.startswith("services.")):
                _sys.modules[f"_oa.{_n}"] = _sys.modules.pop(_n)
        # Satın Alma'in orijinal modüllerini geri yükle
        _sys.modules.update(_stash)
        if _oa_dir in _sys.path:
            _sys.path.remove(_oa_dir)
    return _app


_operasyon_app = _mount_operasyon()
app.mount("/operasyon", _operasyon_app)