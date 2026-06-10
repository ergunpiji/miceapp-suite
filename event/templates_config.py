"""
Merkezi Jinja2Templates örneği — tüm router'lar bu modülden import eder.
Böylece app.py'de tanımlanan özel filter'lar her yerde çalışır.
"""

import json
from datetime import datetime
from typing import Any, Union
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def format_date_tr(value: Any) -> str:
    """YYYY-MM-DD → GG.AA.YYYY"""
    if not value:
        return "—"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d.%m.%Y")
        # ISO formatındaki stringleri parse etmeye çalış (örn: "2023-10-27")
        dt = datetime.fromisoformat(str(value).split()[0])
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return str(value)


def format_money(value: Any) -> str:
    if value is None:
        return "₺0,00"
    try:
        # Eğer değer string ve virgüllü ise noktaya çevir (örn: "15,50" -> 15.50)
        if isinstance(value, str):
            value = value.replace(".", "").replace(",", ".")
        amount = float(value)
        return f"₺{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "₺0,00"


def role_label(role: str) -> str:
    labels = {
        "admin":           "Sistem Yöneticisi",
        "mudur":           "Müdür",
        "yonetici":        "Proje Yöneticisi",
        "asistan":         "Proje Asistanı",
        "project_manager": "Proje Yöneticisi",   # geriye uyumluluk
        "satinalma":           "Satın Alma (Satın Alma)",
        "muhasebe_muduru": "Muhasebe Müdürü",
        "muhasebe":        "Muhasebe Yetkilisi",
    }
    return labels.get(role, role)


def fromjson_filter(value: Any) -> Any:
    """JSON string → Python object (Jinja2 filter)"""
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value or {}
    except Exception:
        return {}


def format_datetime_tr(value: Any) -> str:
    """datetime veya ISO string → GG.AA.YYYY SS:DD"""
    if not value:
        return "—"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d.%m.%Y %H:%M")
        s = str(value)[:16].replace("T", " ")   # "2026-04-20T14:30" → "2026-04-20 14:30"
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


_company_name_cache: dict[str, str] = {}


def company_name(company_id: Any) -> str:
    """company_id → şirket adı (paylaşılan companies tablosundan, cache'li).
    Event'te Company modeli yok; raw SQL ile okunur."""
    if not company_id:
        return ""
    cid = str(company_id)
    if cid in _company_name_cache:
        return _company_name_cache[cid]
    name = ""
    try:
        from database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            row = db.execute(text("SELECT name FROM companies WHERE id = :id"), {"id": cid}).fetchone()
            name = (row[0] if row else "") or ""
        finally:
            db.close()
    except Exception:
        name = ""
    _company_name_cache[cid] = name
    return name


templates.env.filters["date_tr"]      = format_date_tr
templates.env.filters["datetime_tr"]  = format_datetime_tr
templates.env.filters["money"]        = format_money
templates.env.filters["role_label"]   = role_label
templates.env.filters["fromjson"]     = fromjson_filter
def switch_companies() -> list:
    """super_admin şirket seçici için (id, name) listesi."""
    try:
        from database import SessionLocal
        from models import Company
        db = SessionLocal()
        try:
            return [(c.id, c.name) for c in
                    db.query(Company).filter(Company.active == True).order_by(Company.name).all()]
        finally:
            db.close()
    except Exception:
        return []


def active_company_label(user) -> str:
    """super_admin için aktif şirket etiketi; aktif yoksa 'Tüm Şirketler (konsolide)'.
    Diğer kullanıcılar için kendi şirket adı."""
    if user is None:
        return ""
    if getattr(user, "role", None) == "super_admin":
        ac = getattr(user, "_active_company_id", None)
        if not ac:
            return "Tüm Şirketler (konsolide)"
        return company_name(ac) or "Tüm Şirketler (konsolide)"
    return company_name(getattr(user, "company_id", None))


def desk_url() -> str:
    """Desk (finans/İK) app URL'i — event'ten desk sayfalarına link için."""
    try:
        from auth import DESK_URL
        return DESK_URL
    except Exception:
        return "https://desk.miceapp.net"


templates.env.globals["company_name"] = company_name
templates.env.globals["switch_companies"] = switch_companies
templates.env.globals["active_company_label"] = active_company_label
templates.env.globals["desk_url"] = desk_url
